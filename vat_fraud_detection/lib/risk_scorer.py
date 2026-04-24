"""Dynamic risk scoring for VAT compliance analysis results.

Risk Score (0–100) is a weighted composite of three components:

  materiality   (50%) — how much VAT exposure is at stake in euros
  rule_severity (30%) — how clear-cut the violation is across line items
  historical    (20%) — how often this supplier has had issues in past runs

Risk tier:
  HIGH   ≥ 70
  MEDIUM 35–69
  LOW    < 35
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from lib.models import AnalysisResult, VATVerdict


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

RiskTier = Literal["HIGH", "MEDIUM", "LOW"]

@dataclass
class RiskScore:
    result_id: str
    invoice_ref: str          # invoice_number or source_file

    # raw sub-scores (0–100)
    materiality_score: float
    rule_severity_score: float
    historical_score: float

    # final weighted composite
    total_score: float
    tier: RiskTier

    # supporting detail (for rationale display)
    vat_exposure_eur: float       # total monetary exposure
    n_incorrect: int
    n_uncertain: int
    n_correct: int
    supplier_name: str
    supplier_vat: str
    invoice_date: str
    past_issue_count: int         # from historical look-up


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _materiality_score(verdicts: list[VATVerdict]) -> tuple[float, float]:
    """Return (score 0-100, total VAT exposure in EUR)."""
    exposure = 0.0
    for v in verdicts:
        if v.verdict in ("incorrect", "uncertain") and v.expected_rate is not None:
            gap = abs(v.applied_rate - v.expected_rate)
            # Estimate the net-of-VAT amount from the applied total:
            # total_incl_vat is not available here; use vat_amount as proxy.
            # vat_gap ≈ gap / v.applied_rate * v.applied_rate = gap * base
            # We approximate base ≈ v.applied_rate and gap contribution.
            # Since we don't have line totals in VATVerdict, use a fixed unit.
            # A rough proxy: exposure += gap * 1000 (assume €1k base per item).
            # Callers who have LineItem totals should pass those in; this is the
            # general-purpose fallback.
            exposure += gap * 1_000
    # Soft cap at €20,000 → score 100; log-scaled for sensitivity at low values
    score = min(100.0, math.log10(1 + exposure) / math.log10(1 + 20_000) * 100)
    return round(score, 1), round(exposure, 2)


def _materiality_score_with_items(
    result: AnalysisResult,
) -> tuple[float, float]:
    """Materiality using actual LineItem totals for accurate exposure."""
    verdict_map = {v.line_item_id: v for v in result.verdicts}
    exposure = 0.0
    for li in result.invoice.line_items:
        v = verdict_map.get(li.id)
        if v and v.verdict in ("incorrect", "uncertain") and v.expected_rate is not None:
            # base = total excl. VAT = total_incl_vat / (1 + applied_rate)
            if li.total_incl_vat and li.vat_rate_applied > 0:
                base = li.total_incl_vat / (1 + li.vat_rate_applied)
            elif li.unit_price and li.quantity:
                base = li.unit_price * li.quantity
            else:
                base = 1_000  # fallback estimate
            gap = abs(li.vat_rate_applied - v.expected_rate)
            exposure += gap * base
    score = min(100.0, math.log10(1 + exposure) / math.log10(1 + 20_000) * 100)
    return round(score, 1), round(exposure, 2)


def _rule_severity_score(verdicts: list[VATVerdict]) -> float:
    """Average per-item severity: incorrect→100, uncertain→30, correct→0."""
    if not verdicts:
        return 0.0
    weights = {"incorrect": 100.0, "uncertain": 30.0, "correct": 0.0}
    total = sum(weights.get(v.verdict, 0.0) for v in verdicts)
    return round(total / len(verdicts), 1)


def _historical_score(supplier_name: str, supplier_vat: str,
                      past_results: list[AnalysisResult]) -> tuple[float, int]:
    """Count past non-correct verdicts for this supplier; map to 0-100."""
    if not past_results:
        return 0.0, 0

    name_key = (supplier_name or "").strip().lower()
    vat_key  = (supplier_vat or "").strip().upper()

    issue_count = 0
    for r in past_results:
        inv = r.invoice
        match = (
            (vat_key  and inv.supplier_vat_number.strip().upper() == vat_key)
            or (name_key and inv.supplier_name.strip().lower() == name_key)
        )
        if match and r.overall_verdict != "correct":
            issue_count += 1

    # 5+ past issues → score 100
    score = min(100.0, issue_count * 20)
    return round(score, 1), issue_count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_result(
    result: AnalysisResult,
    past_results: list[AnalysisResult] | None = None,
) -> RiskScore:
    """Compute a RiskScore for *result*, optionally considering history."""
    past = past_results or []

    mat_score, exposure = _materiality_score_with_items(result)
    sev_score           = _rule_severity_score(result.verdicts)
    hist_score, n_past  = _historical_score(
        result.invoice.supplier_name,
        result.invoice.supplier_vat_number,
        past,
    )

    total = round(0.50 * mat_score + 0.30 * sev_score + 0.20 * hist_score, 1)

    if total >= 70:
        tier: RiskTier = "HIGH"
    elif total >= 35:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    n_incorrect = sum(1 for v in result.verdicts if v.verdict == "incorrect")
    n_uncertain = sum(1 for v in result.verdicts if v.verdict == "uncertain")
    n_correct   = sum(1 for v in result.verdicts if v.verdict == "correct")

    inv = result.invoice
    return RiskScore(
        result_id         = result.id,
        invoice_ref       = inv.invoice_number or inv.source_file,
        materiality_score = mat_score,
        rule_severity_score = sev_score,
        historical_score  = hist_score,
        total_score       = total,
        tier              = tier,
        vat_exposure_eur  = exposure,
        n_incorrect       = n_incorrect,
        n_uncertain       = n_uncertain,
        n_correct         = n_correct,
        supplier_name     = inv.supplier_name,
        supplier_vat      = inv.supplier_vat_number,
        invoice_date      = inv.invoice_date,
        past_issue_count  = n_past,
    )


def score_results(
    results: list[AnalysisResult],
) -> list[tuple[AnalysisResult, RiskScore]]:
    """Score all results, using the full list as mutual historical context.

    Returns pairs sorted by total_score descending.
    """
    scored = []
    for r in results:
        # Historical = all *other* saved results (not the current batch)
        past = [x for x in results if x.id != r.id]
        scored.append((r, score_result(r, past)))
    scored.sort(key=lambda t: t[1].total_score, reverse=True)
    return scored
