"""VAT compliance analysis: per-item RAG retrieval + LM Studio LLM verdict."""
from __future__ import annotations

import json
import os
import re
import time

# Strip JS-style // comments that the LLM sometimes injects after values.
# Negative lookbehind on ':' ensures we don't strip :// inside URLs.
_JSON_COMMENT_RE = re.compile(r'(?<!:)//[^\n]*')

from lib.models import Invoice, VATVerdict, AnalysisResult, LegislationRef
from lib import rag
from lib.utils import load_prompt

_LM_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
_LM_MODEL    = os.getenv("LM_STUDIO_ANALYSIS_MODEL",
               os.getenv("LM_STUDIO_MODEL", "mistralai/mistral-7b-instruct-v0.3"))


def analyse(invoice: Invoice) -> AnalysisResult:
    from lib import analysis_log
    _t0 = time.perf_counter()
    """Run full RAG + LLM analysis on *invoice* and return an AnalysisResult.

    For each line item we retrieve the most relevant legislation chunks,
    deduplicate across items, then send the combined context to LM Studio
    to produce a verdict per line item.
    """
    from openai import OpenAI
    from tenacity import retry, stop_after_attempt, wait_exponential

    # Retrieve legislation context — one call per line item so the query is
    # tailored to each description + category.
    all_chunks: list[dict] = []
    for item in invoice.line_items:
        all_chunks.extend(rag.retrieve(item))

    # Deduplicate and cap to keep the prompt focused.
    context_chunks = rag.deduplicate(all_chunks)[:12]
    context = rag.format_context(context_chunks)

    # Map ref number → chunk text so we can attach paragraphs after parsing
    ref_to_text = {f"[{i}]": chunk["document"] for i, chunk in enumerate(context_chunks, 1)}

    system_prompt = load_prompt("analysis_system.txt")
    invoice_json  = _invoice_summary(invoice)

    # Mistral-family prompt templates loaded in LM Studio reject the
    # separate "system" role ("Only user and assistant roles are
    # supported!"). Prepend the instructions to the user turn with
    # a clear separator — semantically equivalent for a one-shot
    # query and works with every chat template we ship with.
    user_content = (
        f"{system_prompt}\n\n"
        f"-----\n"
        f"## Invoice\n{invoice_json}\n\n"
        f"## Relevant VAT Legislation\n"
        f"{context or 'No legislation documents are available.'}"
    )

    client = OpenAI(base_url=_LM_BASE_URL, api_key="lm-studio")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _call() -> str:
        response = client.chat.completions.create(
            model=_LM_MODEL,
            max_tokens=4096,
            temperature=0.0,
            messages=[
                {"role": "user", "content": user_content},
            ],
        )
        return response.choices[0].message.content

    raw = _call().strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = _JSON_COMMENT_RE.sub("", raw)

    verdicts: list[VATVerdict] = []
    try:
        data = json.loads(raw)
        for v in data.get("verdicts", []):
            refs: list[LegislationRef] = []
            for r in v.get("legislation_refs", []):
                if isinstance(r, dict):
                    ref_key = r.get("ref", "")
                    refs.append(LegislationRef(
                        ref=ref_key,
                        source=r.get("source", ""),
                        url=r.get("url", ""),
                        section=r.get("section", ""),
                        page=str(r.get("page", "")),
                        paragraph=ref_to_text.get(ref_key, ""),
                    ))
                else:
                    # Fallback: plain string ref from older schema
                    refs.append(LegislationRef(source=str(r), url="", section=""))
            # The LLM occasionally returns non-numeric rate values (e.g.
            # "uncertain") instead of floats — tolerate that by falling
            # back to None / 0.0 rather than raising.
            def _to_float(x, default):
                try:
                    return float(x)
                except (TypeError, ValueError):
                    return default
            applied = _to_float(v.get("applied_rate"), 0.0)
            expected = _to_float(v.get("expected_rate"), None)
            verdicts.append(VATVerdict(
                line_item_id=str(v.get("line_item_id", "")),
                applied_rate=applied,
                expected_rate=expected,
                verdict=v.get("verdict", "uncertain"),
                reasoning=v.get("reasoning", ""),
                legislation_refs=refs,
            ))
    except (json.JSONDecodeError, KeyError):
        pass

    result = AnalysisResult(
        invoice=invoice,
        verdicts=verdicts,
        overall_verdict=_overall_verdict(verdicts),
        model_used=_LM_MODEL,
    )
    analysis_log.write_log(
        invoice_number=invoice.invoice_number or invoice.source_file,
        supplier_name=invoice.supplier_name or "",
        model_used=_LM_MODEL,
        line_items_count=len(invoice.line_items),
        overall_verdict=result.overall_verdict,
        response_time_ms=(time.perf_counter() - _t0) * 1000,
    )
    return result


def _overall_verdict(verdicts: list[VATVerdict]) -> str:
    if not verdicts:
        return "uncertain"
    if any(v.verdict == "incorrect" for v in verdicts):
        return "incorrect"
    if all(v.verdict == "correct" for v in verdicts):
        return "correct"
    return "uncertain"


def _invoice_summary(invoice: Invoice) -> str:
    items = [
        {
            "id": li.id,
            "description": li.description,
            "product_category": li.product_category,
            "quantity": li.quantity,
            "unit_price": li.unit_price,
            "vat_rate_applied": f"{li.vat_rate_applied:.1%}",
            "vat_amount": li.vat_amount,
            "total_incl_vat": li.total_incl_vat,
        }
        for li in invoice.line_items
    ]
    # The jurisdiction whose VAT law applies is the DESTINATION country —
    # this is a cross-border B2C import, so the OSS/IOSS rules of the
    # destination determine the correct VAT rate. supplier_country (where
    # goods ship from) is non-EU and informational only. Label both
    # clearly so the LLM doesn't anchor on the supplier's country.
    return json.dumps({
        "invoice_number":      invoice.invoice_number,
        "supplier":            invoice.supplier_name,
        "supplier_vat":        invoice.supplier_vat_number,
        "customer":            invoice.customer_name,
        "country_of_origin":   invoice.supplier_country,
        "country_of_destination (VAT jurisdiction to apply)": invoice.destination_country,
        "date":                invoice.invoice_date,
        "currency":            invoice.currency,
        "line_items":          items,
    }, indent=2)
