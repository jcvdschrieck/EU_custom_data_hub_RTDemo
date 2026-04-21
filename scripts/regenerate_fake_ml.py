"""
Regenerate Context/Fake_ML.xlsx — per-transaction expected engine outputs.

The new dataset's risk engines (Stage 2) read this file to obtain pre-baked
per-tx outputs so each xlsx row lands exactly on its target route. This
replaces the old aggregate (seller × origin × cat × destination) Fake ML
rule format, which couldn't reproduce per-row labels.

Schema (one row per source-xlsx tx):

    xlsx_row_index               position in source xlsx (0-based)
    seller_name, origin, destination, vat_parent_category, vat_subcategory_code
    declared_vat_rate, recommended_vat_rate     (fractions, 0..1)
    expected_vat_ratio_risk      (0/1) — vat_ratio engine target
    expected_ml_risk             (0..1) — ML engine target (Score 3/100)
    expected_vagueness_risk      (0..1) — vagueness engine target (Score 2/100)
    seller_contribution          per-dimension weights for ml_risk
    country_origin_contribution
    category_contribution
    destination_contribution
    expected_overall_risk        (0..1)
    expected_route               release / investigate / retain
    expected_risk_level          Low / Medium / High

Run this after editing the source xlsx. Idempotent — overwrites the target.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT       = Path(__file__).resolve().parent.parent
SOURCE     = ROOT / "Context" / "VAT_Cases_Generated_17042026_6.xlsx"
TARGET     = ROOT / "Context" / "Fake_ML.xlsx"


def _route_from_action(action: str) -> str:
    return {"release": "release", "investigate": "investigate", "retain": "retain"}[
        (action or "").strip().lower()
    ]


def main() -> None:
    tx = pd.read_excel(SOURCE, sheet_name="VAT Missclassification Last")

    rows: list[dict] = []
    for idx, r in tx.iterrows():
        decl_rate = float(r["VAT Rate (%)"]) / 100.0
        rec_rate  = float(r["VAT Rate (Recommended)"]) / 100.0
        ml_risk   = float(r["Score 3"]) / 100.0
        vague     = float(r["Score 2"]) / 100.0

        # vat_ratio engine target = Score 1 / 100, gated by actual rate
        # mismatch. The xlsx zeroes out Score 1's contribution to the
        # Overall Risk Score whenever declared_rate == recommended_rate
        # (categories may differ, but if no revenue is at stake, the
        # vat_ratio engine should not fire). Without this gate, ~13 rows
        # would be mis-routed.
        rate_mismatch = abs(decl_rate - rec_rate) > 1e-9
        vat_ratio = (float(r["Score 1"]) / 100.0) if rate_mismatch else 0.0

        # ML risk attribution. The xlsx encodes supplier risk only via
        # Score 3 — i.e. "the seller looked suspicious." We attribute the
        # full risk to the seller dimension. If a future model factors in
        # origin/category/destination separately, split accordingly.
        if ml_risk > 0:
            contrib = {"seller": 1.0, "origin": 0.0, "category": 0.0, "destination": 0.0}
        else:
            contrib = {"seller": 0.0, "origin": 0.0, "category": 0.0, "destination": 0.0}

        rows.append({
            "xlsx_row_index":               int(idx),
            "seller_name":                  r["Seller"],
            "origin":                       r["Origin Country"],
            "destination":                  r["Destination Country"],
            "vat_parent_category":          r["VAT Category (declared)"],
            "vat_subcategory_code":         r["VAT Code (declared)"],
            "declared_vat_rate":            round(decl_rate, 4),
            "recommended_vat_rate":         round(rec_rate, 4),
            "expected_vat_ratio_risk":      vat_ratio,
            "expected_ml_risk":             round(ml_risk, 4),
            "expected_vagueness_risk":      round(vague, 4),
            "seller_contribution":          contrib["seller"],
            "country_origin_contribution":  contrib["origin"],
            "category_contribution":        contrib["category"],
            "destination_contribution":     contrib["destination"],
            "expected_overall_risk":        round(float(r["Overall Risk Score (Calculated)"]) / 100.0, 4),
            "expected_route":               _route_from_action(r["Customs Authority Action (Calculated)"]),
            "expected_risk_level":          r["Overall Risk Level"],
        })

    out = pd.DataFrame(rows)
    with pd.ExcelWriter(TARGET, engine="openpyxl") as w:
        out.to_excel(w, sheet_name="Per-Tx Expected Engine Outputs", index=False)

    print(f"Wrote {TARGET.relative_to(ROOT)} — {len(out)} rows")
    print()
    print("Route distribution:")
    print(out["expected_route"].value_counts().to_string())
    print()
    print("Per-engine flag rate:")
    print(f"  vat_ratio flagged (>=0.5): {(out['expected_vat_ratio_risk'] >= 0.5).sum()}")
    print(f"  ml flagged (>=0.5):        {(out['expected_ml_risk'] >= 0.5).sum()}")
    print(f"  vagueness flagged (>=0.5): {(out['expected_vagueness_risk'] >= 0.5).sum()}")


if __name__ == "__main__":
    main()
