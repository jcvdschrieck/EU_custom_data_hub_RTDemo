"""
Inject two demo cases into simulation.db so they appear on the Customs
Authority dashboard within the first two sim-minutes.

    Case 1 — VAT Misclassification (ambiguity-driven)
            ShenZhen TechGlobal Co. × IE × COSMETICS & PERSONAL CARE
            Bone-conduction headset declared as CO-06 ("Pharmaceutical /
            medicinal product", IE 0%) though the product is consumer
            electronics that should attract 23% under EL-01.
            Stronger signal: vat_ratio.  Case-level score ≈ 0.71 (High).

            + 4 historical closed cases (2 retained / 2 released) in
              historical_cases.db so _compute_customs_recommendation
              routes to "Submit for Tax Review" (50% retention rate).

    Case 2 — Vague Description
            Delhi PharmaExport Pvt Ltd × IE × FOOD SUPPLEMENTS & VITAMINS
            "Capsules for daily health support" under FS-02 (IE 0%).
            No rate mismatch — only signal is vagueness.
            Case-level score ≈ 0.65 (Medium), vagueness ≥ 0.5 so
            _compute_customs_recommendation emits
            "Request Input from Deemed Importer".

Both clusters use the same Jaccard-anchor marker convention as the
main seeder so every order lands in a single open case via
find_similar_open_case.

Run with the venv active (or directly with `python3`):
    python3 scripts/inject_demo_cases.py

The script is idempotent — it deletes any prior rows tagged with the
demo cluster markers before re-inserting, so you can re-run it after
`python seed_databases.py` whenever you need to refresh the demo state.
"""
from __future__ import annotations

import random
import sqlite3
import sys
import uuid
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.config     import SIM_START_DT, SIMULATION_DB, HISTORICAL_CASES_DB
from lib.database   import bulk_insert, init_historical_cases_db, _connect
from lib            import vat_dataset


# ── Cluster marker helpers (mirror lib/new_seeder.py) ──────────────────────

def _seller_code(seller_name: str) -> str:
    parts = [w[:3].upper() for w in seller_name.split() if w[0].isupper()]
    return "".join(parts[:2]) or "GEN"


def _category_code(parent_category: str) -> str:
    return "".join(w[0].upper() for w in parent_category.split() if w[0].isalpha())[:3]


def _cluster_markers(seller: str, destination: str, parent: str) -> str:
    cid = f"{_seller_code(seller)}-{destination}-{_category_code(parent)}"
    return (
        f"lot-{cid} ref-{cid} shipment-{cid} "
        f"batch-{cid} manifest-{cid} series-{cid}"
    )


def _new_tx_id(rng: random.Random) -> str:
    return f"TX-{uuid.UUID(int=rng.getrandbits(128)).hex[:12].upper()}"


# ── Demo-case specs ────────────────────────────────────────────────────────

CASE_1 = {
    "seller_name":       "ShenZhen TechGlobal Co.",
    "destination":       "IE",
    "parent_category":   "COSMETICS & PERSONAL CARE",          # declared
    "subcategory_code":  "CO-06",                              # Pharmaceutical / medicinal product → IE 0%
    "declared_rate":     0.0,
    "correct_rate":      0.23,                                 # real classification: Electronics 23%
    "has_error":         1,
    "n_orders":          25,
    "base_value":        85.0,
    "base_description":  "Open-ear bone conduction sport headset, 8-hour battery, hearing-assistance positioning (no medical certification)",
    # Engine scores — vat_ratio dominates; case-level score ≈ 0.71 (High)
    "engine_vat_ratio":  0.90,
    "engine_ml":         0.20,
    "engine_ie_wl":      0.0,
    "engine_vagueness":  0.10,
}

CASE_2 = {
    "seller_name":       "Delhi PharmaExport Pvt Ltd",
    "destination":       "IE",
    "parent_category":   "FOOD SUPPLEMENTS & VITAMINS",        # declared
    "subcategory_code":  "FS-02",                              # Omega / fatty acids → IE 0%
    "declared_rate":     0.0,
    "correct_rate":      0.0,                                  # no misclass; vagueness is the sole driver
    "has_error":         0,
    "n_orders":          25,
    "base_value":        120.0,
    "base_description":  "Capsules for daily health support",
    # Engine scores — vagueness dominates; case-level score ≈ 0.65 (Medium)
    "engine_vat_ratio":  0.0,
    "engine_ml":         0.10,
    "engine_ie_wl":      0.0,
    "engine_vagueness":  0.65,
}


# ── Transaction builder ────────────────────────────────────────────────────

def _build_tx_rows(case: dict, rng: random.Random) -> list[dict]:
    """Build N transactions for a cluster, all stamped in the first 120 s
    of the sim window so they arrive on the Customs queue within the
    first two sim-minutes.  Values cluster tightly (±11 % of base) so the
    max/min ratio across orders stays ≤ 1.25."""
    seller = vat_dataset.seller_by_name(case["seller_name"])
    if not seller:
        raise RuntimeError(f"Unknown seller: {case['seller_name']}")

    markers = _cluster_markers(case["seller_name"], case["destination"], case["parent_category"])
    base    = case["base_value"]
    rows: list[dict] = []

    # Distribute the first 120 seconds evenly across the cluster.
    for i in range(case["n_orders"]):
        offset_s = 5 + (115 * i) / max(1, case["n_orders"] - 1)
        ts = (SIM_START_DT + timedelta(seconds=offset_s)).isoformat()

        value = round(rng.uniform(base * 0.894, base * 1.118), 2)
        vat_amount = round(value * case["declared_rate"], 2)

        description = (
            f"{case['base_description']} unit {i + 1:03d} — {markers}"
        )

        rows.append({
            "transaction_id":                     _new_tx_id(rng),
            "transaction_date":                   ts,
            "seller_id":                          seller["id"],
            "seller_name":                        seller["name"],
            "seller_country":                     seller["origin"],
            "item_description":                   description,
            "item_category":                      case["parent_category"],
            "value":                              value,
            "vat_rate":                           case["declared_rate"],
            "vat_amount":                         vat_amount,
            "buyer_country":                      case["destination"],
            "correct_vat_rate":                   case["correct_rate"],
            "has_error":                          case["has_error"],
            "xml_message":                        None,
            "created_at":                         ts,
            "producer_id":                        None,
            "producer_name":                      None,
            "producer_country":                   None,
            "producer_city":                      None,
            "vat_subcategory_code":               case["subcategory_code"],
            "engine_vat_ratio_risk":              case["engine_vat_ratio"],
            "engine_ml_risk":                     case["engine_ml"],
            "engine_ml_seller_contribution":      0.0,
            "engine_ml_origin_contribution":      0.0,
            "engine_ml_category_contribution":    0.0,
            "engine_ml_destination_contribution": 0.0,
            "engine_vagueness_risk":              case["engine_vagueness"],
            "engine_ie_watchlist_risk":           case["engine_ie_wl"],
        })
    return rows


# ── Historical cases for Case 1's "Submit for Tax Review" rec ──────────────

_HIST_OUTCOMES = [
    # 2 retained + 2 released → 50% retention → "Submit for Tax Review"
    ("retain",  "2025-11-12"),
    ("retain",  "2026-01-08"),
    ("release", "2025-12-04"),
    ("release", "2026-02-17"),
]


def _inject_historical_cases(case: dict) -> int:
    """Create 4 past closed cases for Case 1 in historical_cases.db so
    the Submit-for-Tax-Review branch of _compute_customs_recommendation
    fires.  Rows fit the same 3-table schema the historical seeder uses.
    """
    init_historical_cases_db()
    conn = _connect(HISTORICAL_CASES_DB)

    rng = random.Random(42)
    seller       = vat_dataset.seller_by_name(case["seller_name"])
    origin       = seller["origin"] if seller else "CN"
    inserted = 0

    with conn:
        for action, ts_case in _HIST_OUTCOMES:
            case_id = f"CASE-H-DEMO-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"
            so_bk   = f"SOH-DEMO-{uuid.UUID(int=rng.getrandbits(128)).hex[:12].upper()}"

            # Delete any prior demo row keyed on the same case_id so the
            # script stays idempotent across re-runs.
            conn.execute("DELETE FROM Sales_Order_Case WHERE Case_ID LIKE 'CASE-H-DEMO-%' "
                         "AND Sales_Order_Business_Key IN ("
                         "   SELECT Sales_Order_Business_Key FROM Sales_Order "
                         "   WHERE Seller_Name = ? AND HS_Product_Category = ? "
                         "   AND Country_Destination = ?"
                         ")", (case["seller_name"], case["parent_category"], case["destination"]))

            # 1 order per case is enough to satisfy get_previous_cases' JOIN.
            value    = round(rng.uniform(70, 100), 2)
            applied  = 0.0
            vat_fee  = 0.0

            conn.execute(
                "INSERT INTO Sales_Order "
                "(Sales_Order_ID, Sales_Order_Business_Key, HS_Product_Category, "
                " Product_Description, Product_Value, VAT_Rate, VAT_Fee, Seller_Name, "
                " Country_Origin, Country_Destination, Status, Update_time, Updated_by, Case_ID) "
                "VALUES (:so_id, :so_bk, :cat, :desc, :val, :rate, :fee, :seller, "
                " :origin, :dest, 'Closed', :ts, 'demo_inject', :cid)",
                {
                    "so_id":  f"SO-HIS-DEMO-{case_id[-8:]}",
                    "so_bk":  so_bk,
                    "cat":    case["parent_category"],
                    "desc":   f"Historical bone-conduction headset order — demo backfill ({action})",
                    "val":    value,
                    "rate":   applied,
                    "fee":    vat_fee,
                    "seller": case["seller_name"],
                    "origin": origin,
                    "dest":   case["destination"],
                    "ts":     f"{ts_case} 10:00",
                    "cid":    case_id,
                },
            )
            conn.execute(
                "INSERT INTO Sales_Order_Risk "
                "(Sales_Order_Business_Key, Risk_Type, Overall_Risk_Score, Overall_Risk_Level, "
                " Seller_Risk_Score, Country_Risk_Score, Product_Category_Risk_Score, "
                " Manufacturer_Risk_Score, Confidence_Score, Proposed_Risk_Action, "
                " Overall_Risk_Description, Update_time) "
                "VALUES (:so_bk, 'Demo', :score, 'Medium', 0.6, 0.5, 0.5, 0.5, 0.7, :prop, "
                "        'Demo backfill for Submit-for-Tax-Review recommendation', :ts)",
                {
                    "so_bk": so_bk,
                    "score": 0.55,
                    "prop":  action,
                    "ts":    f"{ts_case} 10:00",
                },
            )
            conn.execute(
                "INSERT INTO Sales_Order_Case "
                "(Case_ID, Sales_Order_Business_Key, Status, VAT_Problem_Type, "
                " Recommended_Product_Value, Recommended_VAT_Product_Category, "
                " Recommended_VAT_Rate, Recommended_VAT_Fee, AI_Analysis, AI_Confidence, "
                " VAT_Gap_Fee, Evaluation_by, Proposed_Action_Tax, Proposed_Action_Customs, "
                " Communication, Additional_Evidence, Update_time, Updated_by, Created_time, "
                " Overall_Case_Risk_Score, Overall_Case_Risk_Level, "
                " Engine_VAT_Ratio, Engine_ML_Watchlist, Engine_IE_Seller_Watchlist, "
                " Engine_Description_Vagueness) "
                "VALUES (:cid, :so_bk, 'Closed', 'VAT category misclassification', "
                " NULL, 'ELECTRONICS & ACCESSORIES', 0.23, NULL, NULL, NULL, "
                " :gap, 'demo_inject', :pa_tax, :pa_customs, '[]', NULL, "
                " :ts, 'demo_inject', :ts, "
                " 0.55, 'Medium', 0.7, 0.2, 0.0, 0.1)",
                {
                    "cid":        case_id,
                    "so_bk":      so_bk,
                    "gap":        round(value * 0.23, 2),
                    "pa_tax":     "risk_confirmed" if action == "retain" else "no_limited_risk",
                    "pa_customs": action,
                    "ts":         f"{ts_case} 10:00",
                },
            )
            inserted += 1

    conn.close()
    return inserted


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    rng = random.Random(20260424)

    # 1) Delete any prior demo rows in simulation.db so the script is idempotent.
    conn = sqlite3.connect(SIMULATION_DB)
    with conn:
        for case in (CASE_1, CASE_2):
            marker_fragment = f"{_seller_code(case['seller_name'])}-{case['destination']}-{_category_code(case['parent_category'])}"
            conn.execute(
                "DELETE FROM transactions WHERE item_description LIKE ?",
                (f"%lot-{marker_fragment}%",),
            )
    conn.close()

    # 2) Build + bulk-insert simulation.db rows.
    all_rows: list[dict] = []
    for case in (CASE_1, CASE_2):
        rows = _build_tx_rows(case, rng)
        print(f"  {case['seller_name']:<32} × {case['destination']} × {case['parent_category']:<32}  "
              f"{len(rows)} orders, first tx @ {rows[0]['transaction_date']}")
        all_rows.extend(rows)

    bulk_insert(all_rows, path=SIMULATION_DB)
    print(f"✓ {len(all_rows)} transactions inserted into {SIMULATION_DB.name}")

    # 3) Historical backfill for Case 1's "Submit for Tax Review" recommendation.
    n_hist = _inject_historical_cases(CASE_1)
    print(f"✓ {n_hist} historical cases inserted into {HISTORICAL_CASES_DB.name} "
          f"(2 retained / 2 released → 50% retention rate)")

    # 4) Reset the `fired` flag for safety — ensures the simulator replays
    #    these rows cleanly from t=0 after a simulation reset.
    conn = sqlite3.connect(SIMULATION_DB)
    with conn:
        conn.execute("UPDATE transactions SET fired = 0 WHERE fired IS NOT 0")
    conn.close()

    print("\nTo see the cases:")
    print("  1. POST http://localhost:<backend>/api/simulation/reset   (or refresh the dashboard)")
    print("  2. Click ▶ Start on the Simulation page")
    print("  → The two demo cases should surface on the Customs Authority page "
          "within the first two sim-minutes.")


if __name__ == "__main__":
    main()
