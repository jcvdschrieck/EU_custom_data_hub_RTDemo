"""LLM-synthesised risk rationale for high-risk VAT compliance cases.

Builds a structured rationale consisting of:
  1. top_factors  — ordered list of contributing factor dicts
  2. narrative    — plain-English paragraph from LM Studio
  3. data_links   — pointers back to specific verdicts / legislation refs
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from lib.models import AnalysisResult
from lib.risk_scorer import RiskScore

log = logging.getLogger(__name__)

_LM_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
_LM_MODEL    = os.getenv("LM_STUDIO_ANALYSIS_MODEL",
               os.getenv("LM_STUDIO_MODEL", "mistralai/mistral-7b-instruct-v0.3"))


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Rationale:
    top_factors: list[dict]       # [{"label": str, "detail": str, "weight": float}]
    narrative: str                # LLM paragraph
    data_links: list[dict]        # [{"line_item_id": str, "description": str, "verdict": str, "sources": list[str]}]


# ---------------------------------------------------------------------------
# Factor extraction (rule-based, fast, no LLM)
# ---------------------------------------------------------------------------

def _extract_factors(result: AnalysisResult, risk: RiskScore) -> list[dict]:
    """Derive top contributing factors from the result + risk score."""
    factors: list[dict] = []

    # 1. Monetary exposure
    if risk.vat_exposure_eur > 0:
        factors.append({
            "label":  "VAT Monetary Exposure",
            "detail": f"Estimated VAT gap of €{risk.vat_exposure_eur:,.2f} across "
                      f"{risk.n_incorrect} incorrect and {risk.n_uncertain} uncertain line item(s).",
            "weight": risk.materiality_score,
        })

    # 2. Incorrect line items
    incorrect = [v for v in result.verdicts if v.verdict == "incorrect"]
    if incorrect:
        descriptions = ", ".join(
            f"item {v.line_item_id} "
            f"({v.applied_rate:.0%} applied vs {v.expected_rate:.0%} expected)"
            for v in incorrect[:3]
        )
        if len(incorrect) > 3:
            descriptions += f" … and {len(incorrect) - 3} more"
        factors.append({
            "label":  "Confirmed VAT Rate Errors",
            "detail": f"{len(incorrect)} line item(s) with incorrect VAT rate: {descriptions}.",
            "weight": risk.rule_severity_score,
        })

    # 3. Uncertain items
    uncertain = [v for v in result.verdicts if v.verdict == "uncertain"]
    if uncertain:
        factors.append({
            "label":  "Ambiguous VAT Classification",
            "detail": f"{len(uncertain)} line item(s) could not be conclusively classified. "
                      "These require manual review.",
            "weight": round(risk.rule_severity_score * 0.3, 1),
        })

    # 4. Historical pattern
    if risk.past_issue_count > 0:
        factors.append({
            "label":  "Supplier Historical Issues",
            "detail": f"Supplier '{risk.supplier_name}' has {risk.past_issue_count} "
                      "prior invoice(s) with non-correct verdicts in this session.",
            "weight": risk.historical_score,
        })

    # Sort by weight descending
    factors.sort(key=lambda f: f["weight"], reverse=True)
    return factors[:5]   # cap at 5


# ---------------------------------------------------------------------------
# Data links
# ---------------------------------------------------------------------------

def _extract_data_links(result: AnalysisResult) -> list[dict]:
    """Build pointers to non-correct verdicts + their legislation sources."""
    links = []
    verdict_map = {v.line_item_id: v for v in result.verdicts}
    inv = result.invoice
    for li in inv.line_items:
        v = verdict_map.get(li.id)
        if v and v.verdict in ("incorrect", "uncertain"):
            sources = list({
                (ref.source or ref.url)
                for ref in v.legislation_refs
                if ref.source or ref.url
            })
            links.append({
                "line_item_id": li.id,
                "description":  li.description,
                "category":     li.product_category or "—",
                "applied_rate": li.vat_rate_applied,
                "expected_rate": v.expected_rate,
                "verdict":      v.verdict,
                "reasoning_excerpt": v.reasoning[:300] + ("…" if len(v.reasoning) > 300 else ""),
                "sources":      sources,
            })
    return links


# ---------------------------------------------------------------------------
# LLM narrative synthesis
# ---------------------------------------------------------------------------

_NARRATIVE_SYSTEM = """\
You are a VAT compliance risk analyst writing a concise executive summary.
Given structured data about an invoice's VAT compliance issues, write a short \
2-3 sentence risk rationale in plain English.

Focus on: what the main risk is, why it matters financially or legally, \
and what action is recommended.
Return ONLY the narrative text — no JSON, no bullet points, no markdown."""


def _llm_narrative(result: AnalysisResult, risk: RiskScore,
                   factors: list[dict]) -> str:
    """Call LM Studio to generate a plain-English risk rationale."""
    from openai import OpenAI
    client = OpenAI(base_url=_LM_BASE_URL, api_key="lm-studio")

    payload = {
        "invoice_ref":    risk.invoice_ref,
        "supplier":       risk.supplier_name,
        "supplier_vat":   risk.supplier_vat,
        "invoice_date":   risk.invoice_date,
        "risk_tier":      risk.tier,
        "risk_score":     risk.total_score,
        "vat_exposure":   f"€{risk.vat_exposure_eur:,.2f}",
        "n_incorrect":    risk.n_incorrect,
        "n_uncertain":    risk.n_uncertain,
        "n_correct":      risk.n_correct,
        "top_factors":    [{"label": f["label"], "detail": f["detail"]}
                           for f in factors],
    }

    # Mistral-family templates reject "system" role — merge into user.
    merged_user = f"{_NARRATIVE_SYSTEM}\n\n-----\n{json.dumps(payload, indent=2)}"
    try:
        resp = client.chat.completions.create(
            model=_LM_MODEL,
            messages=[{"role": "user", "content": merged_user}],
            temperature=0.3,
            max_tokens=256,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        log.warning("LLM narrative generation failed: %s", exc)
        # Deterministic fallback
        tier_phrase = {
            "HIGH":   "represents a HIGH-risk compliance issue",
            "MEDIUM": "presents a MEDIUM-risk compliance concern",
            "LOW":    "is a LOW-risk compliance matter",
        }.get(risk.tier, "requires attention")
        return (
            f"Invoice {risk.invoice_ref} from {risk.supplier_name or 'unknown supplier'} "
            f"{tier_phrase} with a risk score of {risk.total_score}/100. "
            f"An estimated VAT exposure of €{risk.vat_exposure_eur:,.2f} was identified "
            f"across {risk.n_incorrect} incorrect and {risk.n_uncertain} uncertain line item(s). "
            "Manual review and correction of the flagged items is recommended."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_rationale(result: AnalysisResult, risk: RiskScore) -> Rationale:
    """Build a full Rationale for *result* given its *risk* score."""
    factors    = _extract_factors(result, risk)
    data_links = _extract_data_links(result)
    narrative  = _llm_narrative(result, risk, factors)
    return Rationale(
        top_factors = factors,
        narrative   = narrative,
        data_links  = data_links,
    )
