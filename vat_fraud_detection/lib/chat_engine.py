"""Manage multi-turn conversation for the Chat page."""
from __future__ import annotations
import json
import os
from lib.models import Invoice, AnalysisResult
from lib.utils import load_prompt

_CHAT_MODEL = "claude-sonnet-4-6"

def build_system_message(invoice: Invoice | None,
                         result: AnalysisResult | None) -> str:
    base = load_prompt("chat_system.txt")
    if invoice is None:
        return base
    context_parts = [base, "\n\n## Current Invoice Context\n"]
    context_parts.append(f"Supplier: {invoice.supplier_name} ({invoice.supplier_country})")
    context_parts.append(f"Date: {invoice.invoice_date}  |  Number: {invoice.invoice_number}")
    if result:
        context_parts.append(f"Overall verdict: **{result.overall_verdict.upper()}**")
        for v in result.verdicts:
            context_parts.append(
                f"- Line {v.line_item_id}: {v.verdict} "
                f"(applied {v.applied_rate:.0%}, expected {v.expected_rate:.0%})"
                if v.expected_rate is not None else
                f"- Line {v.line_item_id}: {v.verdict}"
            )
    return "\n".join(context_parts)

def stream_response(messages: list[dict], system: str):
    """Yield text chunks from a streaming Claude response."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    with client.messages.stream(
        model=_CHAT_MODEL,
        max_tokens=2048,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
