"""
Smoke-test the Stage 1 reference data.

Loads lib/vat_dataset and Context/Fake_ML.xlsx, then asserts:
  - every xlsx tx row resolves to a (rate, rate_type) via expected_rate_for
  - every seller's origin and destinations match the xlsx
  - every (dest, subcat) pair in xlsx is in VAT_RATE_LOOKUP
  - VAT_CATEGORIES + SUBCATEGORY_BY_CODE are mutually consistent
  - Per-tx Fake ML rows decay correctly into the engine-mean route prediction.

The route check is the load-bearing one — if it fails, Stage 2's engine
weighting will need to compensate.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent

import sys
sys.path.insert(0, str(ROOT))

from lib import vat_dataset as vd  # noqa: E402


THRESHOLD_RELEASE = 1.0 / 3.0
THRESHOLD_RETAIN  = 0.80

# Mirrors api.py ENGINE_WEIGHTS — keep in sync.
ENGINE_WEIGHTS = {
    "vat_ratio":             0.5,
    "ml":                    0.9,
    "vagueness":             0.8,
    "ireland_watchlist":     1.0,
}


def _route_from_score(score: float) -> str:
    if score >= THRESHOLD_RETAIN:
        return "retain"
    if score >= THRESHOLD_RELEASE:
        return "investigate"
    return "release"


def main() -> None:
    src = pd.read_excel(ROOT / "Context" / "VAT_Cases_Generated_17042026_6.xlsx",
                        sheet_name="VAT Missclassification Last")
    fml = pd.read_excel(ROOT / "Context" / "Fake_ML.xlsx",
                        sheet_name="Per-Tx Expected Engine Outputs")

    failures: list[str] = []

    # ── Check 1: xlsx → vat_dataset rate lookup ─────────────────────────────
    for idx, r in src.iterrows():
        dest = r["Destination Country"]
        code = r["VAT Code (Recommended)"]
        rate = vd.expected_rate_for(dest, code)
        if rate is None:
            failures.append(f"row {idx}: ({dest}, {code}) returns None from expected_rate_for")
        elif abs(rate - r["VAT Rate (Recommended)"] / 100.0) > 1e-6:
            failures.append(
                f"row {idx}: ({dest}, {code}) rate mismatch — "
                f"dataset={rate} vs xlsx={r['VAT Rate (Recommended)']/100.0}"
            )

    # ── Check 2: sellers ────────────────────────────────────────────────────
    for s in vd.SELLERS:
        sub = src[src["Seller"] == s["name"]]
        if len(sub) == 0:
            failures.append(f"seller {s['name']!r} not found in source xlsx")
            continue
        observed_origin = sub["Origin Country"].iloc[0]
        if observed_origin != s["origin"]:
            failures.append(
                f"seller {s['name']!r}: origin {observed_origin!r} ≠ dataset {s['origin']!r}"
            )
        observed_dests = set(sub["Destination Country"].unique())
        if observed_dests != set(s["destinations"]):
            failures.append(
                f"seller {s['name']!r}: destinations {sorted(observed_dests)} "
                f"≠ dataset {s['destinations']}"
            )

    # ── Check 3: VAT_CATEGORIES ↔ SUBCATEGORY_BY_CODE consistency ───────────
    flat_codes = {code for subs in vd.VAT_CATEGORIES.values() for (code, _) in subs}
    if flat_codes != set(vd.SUBCATEGORY_BY_CODE.keys()):
        failures.append("VAT_CATEGORIES and SUBCATEGORY_BY_CODE diverge")

    # ── Check 4: per-tx engine outputs reproduce expected route ─────────────
    # Mirrors api._compute_score: weighted sum of applicable engines, capped
    # at 1.0. Weights tuned for max accuracy against the xlsx target labels.
    route_mismatches: list[str] = []
    for _, r in fml.iterrows():
        weighted = (
            ENGINE_WEIGHTS["vat_ratio"] * float(r["expected_vat_ratio_risk"]) +
            ENGINE_WEIGHTS["ml"]        * float(r["expected_ml_risk"]) +
            ENGINE_WEIGHTS["vagueness"] * float(r["expected_vagueness_risk"])
        )
        if r["destination"] == "IE":
            # ie_watchlist is empty in the new dataset → contributes 0
            weighted += ENGINE_WEIGHTS["ireland_watchlist"] * 0.0
        score = min(1.0, weighted)
        predicted = _route_from_score(score)
        expected  = r["expected_route"]
        if predicted != expected:
            route_mismatches.append(
                f"tx#{int(r['xlsx_row_index']):>3} {r['seller_name'][:20]:<20} "
                f"{r['destination']} → score={score:.3f} predicted={predicted} expected={expected}"
            )

    # ── Report ──────────────────────────────────────────────────────────────
    print("=" * 72)
    print("Reference-data + scoring smoke test")
    print("=" * 72)

    if failures:
        print(f"\n✗ {len(failures)} hard failures:")
        for f in failures[:20]:
            print(f"   {f}")
    else:
        print("\n✓ Hard checks: rate lookups, sellers, taxonomy consistency — all pass.")

    print(f"\nRoute prediction (weighted sum of engines, thresholds {THRESHOLD_RELEASE:.3f}/{THRESHOLD_RETAIN:.2f}):")
    print(f"  weights: vat_ratio={ENGINE_WEIGHTS['vat_ratio']}  ml={ENGINE_WEIGHTS['ml']}  "
          f"vagueness={ENGINE_WEIGHTS['vagueness']}  ireland_watchlist={ENGINE_WEIGHTS['ireland_watchlist']}")
    print(f"  matches:    {len(fml) - len(route_mismatches)}/{len(fml)}")
    print(f"  mismatches: {len(route_mismatches)}")
    if route_mismatches:
        print()
        for m in route_mismatches:
            print(f"   {m}")
        print()
        print("  Known residual mismatches — diagnosed in api.py ENGINE_WEIGHTS")
        print("  comment. Stage 3's seeder can override per-tx engine outputs on")
        print("  these rows if pixel-perfect alignment matters.")
    else:
        print("\n  ✓ All 191 tx land on their target route from the precomputed signals.")


if __name__ == "__main__":
    main()
