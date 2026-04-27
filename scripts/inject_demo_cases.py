"""
Inject two demo cases into simulation.db so they appear on the Customs
Authority dashboard within the first two sim-minutes.

Based on xlsx rows 50 and 76 of VAT_Cases_Generated_17042026_6.xlsx,
adapted to the IE destination.

    Case 1 — VAT Misclassification (ambiguity-driven)
            ShenZhen TechGlobal Co. × IE × ELECTRONICS & ACCESSORIES
            Open-ear bone conduction sport headset declared under
            EL-08 "Hearing aid / medical audio device" at IE 0% —
            the recommended classification is EL-03 "Consumer audio
            device" at IE 23%. The product sits in the grey zone:
            bone-conduction IS a legitimate hearing-assistance route,
            but this unit has no medical certification.
            Stronger signal: vat_ratio.  Case-level score ≈ 0.71 (High).

            + 4 historical closed cases (2 retained / 2 released) in
              historical_cases.db so _compute_customs_recommendation
              routes to "Submit for Tax Review" (50% retention rate).

    Case 2 — Vague Description + Supplier Risk
            Delhi PharmaExport Pvt Ltd × IE × COSMETICS & PERSONAL CARE
            "Capsules for daily health support" declared under CO-06
            "Pharmaceutical / medicinal product" at IE 0% (correct —
            no rate mismatch). Signals are vagueness + mild supplier
            risk, matching the "VAT Product Description Vague,
            Supplier Risk" problem the xlsx row 50 reports.
            Case-level score ≈ 0.62 (Medium), vagueness ≥ 0.5 so
            _compute_customs_recommendation emits
            "Request Input from Deemed Importer".

Both clusters use the "-DEMO" suffix on the Jaccard-anchor markers so
they form their own open cases instead of merging into the main
DELPHA-IE-CPC or SHETEC-IE-EA clusters that other demo data may
contribute.

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


def _cluster_markers(seller: str, destination: str, parent: str, suffix: str = "") -> str:
    cid = f"{_seller_code(seller)}-{destination}-{_category_code(parent)}"
    if suffix:
        cid = f"{cid}-{suffix}"
    return (
        f"lot-{cid} ref-{cid} shipment-{cid} "
        f"batch-{cid} manifest-{cid} series-{cid}"
    )


def _new_tx_id(rng: random.Random) -> str:
    # TXDEMO- prefix lets the cleanup DELETE reliably wipe every prior
    # demo row regardless of which cluster / parent / suffix the previous
    # run used. Without it, the deterministic RNG seed produces the same
    # tx_ids across runs, bulk_insert's "INSERT OR IGNORE" skips them,
    # and the stale cluster data survives — so the UI displays the old
    # parents even after you change CASE_1 / CASE_2 in this script.
    return f"TXDEMO-{uuid.UUID(int=rng.getrandbits(128)).hex[:10].upper()}"


# ── Demo-case specs ────────────────────────────────────────────────────────

CASE_1 = {
    "seller_name":       "ShenZhen TechGlobal Co.",
    "destination":       "IE",
    "parent_category":   "ELECTRONICS & ACCESSORIES",          # xlsx row 76 declared parent
    "subcategory_code":  "EL-08",                              # Hearing aid / medical audio device → IE 0% (our add)
    "declared_rate":     0.0,                                  # 0 % zero-rated medical device claim
    "correct_rate":      0.23,                                 # recommended: EL-03 Consumer audio device at IE 23%
    "has_error":         1,
    "n_orders":          25,
    "base_value":        85.0,
    "base_description":  "Open-ear bone conduction sport headset, IP68, 8-hour battery, declared as hearing assistance device (no medical certification)",
    "cluster_suffix":    "DEMO",                               # keeps cluster disjoint from any SHETEC-IE-EA from main dataset
    # Engine scores — vat_ratio dominates; case-level score ≈ 0.71 (High)
    "engine_vat_ratio":  0.90,
    "engine_ml":         0.20,
    "engine_ie_wl":      0.0,
    "engine_vagueness":  0.10,
    # Force the first three ShenZhen orders to fire BEFORE anything in the
    # main dataset (whose earliest tx sits at SIM_START_DT + 0.5 s). With
    # these offsets, ShenZhen is guaranteed to be the first case the operator
    # sees on the Customs dashboard after Start.
    "head_offsets_s":    [0.1, 0.2, 0.3],
}

CASE_2 = {
    "seller_name":       "Delhi PharmaExport Pvt Ltd",
    "destination":       "IE",
    "parent_category":   "COSMETICS & PERSONAL CARE",          # xlsx row 50 declared parent
    "subcategory_code":  "CO-06",                              # Pharmaceutical / medicinal product → IE 0%
    "declared_rate":     0.0,
    "correct_rate":      0.0,                                  # xlsx shows recommended == declared — no rate gap
    "has_error":         0,
    "n_orders":          25,
    "base_value":        120.0,
    "base_description":  "Capsules for daily health support",
    "cluster_suffix":    "DEMO",                               # keeps cluster disjoint from the main DELPHA-IE-CPC cluster
    # Engine scores — vagueness dominates, mild supplier risk per xlsx row 50's
    # "VAT Product Description Vague, Supplier Risk" problem; case-level score ≈ 0.62 (Medium)
    "engine_vat_ratio":  0.0,
    "engine_ml":         0.15,
    "engine_ie_wl":      0.0,
    "engine_vagueness":  0.60,
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

    markers = _cluster_markers(
        case["seller_name"], case["destination"], case["parent_category"],
        suffix=case.get("cluster_suffix", ""),
    )
    base    = case["base_value"]
    rows: list[dict] = []

    # Optional head-offsets: the first len(head_offsets_s) orders use these
    # exact offsets (in seconds after SIM_START_DT), the rest are evenly
    # distributed across [5, 120] s as before. Used to pre-empt the main
    # dataset for the showcase cluster.
    head_offsets_s = case.get("head_offsets_s") or []
    n_head = len(head_offsets_s)
    n_tail = max(1, case["n_orders"] - n_head)

    for i in range(case["n_orders"]):
        if i < n_head:
            offset_s = head_offsets_s[i]
        else:
            j = i - n_head
            offset_s = 5 + (115 * j) / max(1, n_tail - 1)
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
    # 2 retained / 2 released → 50% retention. Drives:
    #   Customs AI Suggestion → "Submit for Tax Review" (in-between
    #     retention, rule routes the case via Tax for a second opinion).
    #   Tax AI Suggestion (post-fraud-agent) → "AI Uncertain" (the
    #     Tax-side rule needs > 75% retention to flip to "Confirm Risk";
    #     50% sits in the in-between band, leaving the call to the
    #     officer with the fraud agent's verdict + VAT gap as evidence).
    # This is the showcase flow: the case visibly travels Customs → Tax
    # → back to Customs, and the operator interacts with the fraud
    # agent + tax conversational agent along the way.
    #
    # Sellers are deliberately DIFFERENT from CASE_1's seller (ShenZhen
    # TechGlobal Co.): in the showcase, ShenZhen is framed as a brand-new
    # seller with no prior history of his own. The "Previous cases" panel
    # (and the Customs/Tax retention rule) match on (category, destination)
    # only — see lib.database.get_previous_cases — so these four still surface
    # as relevant precedents even though they're under different sellers.
    # Tuple shape: (action, date, seller_name, origin_country)
    # Origin uses the full English country name to stay consistent with
    # the rest of historical_cases.db (which is populated by
    # lib.historical_seeder via vat_dataset, returning names like "India"
    # rather than ISO-2 codes).
    ("retain",  "2025-11-12", "Guangzhou Audio Industries Ltd.", "China"),
    ("retain",  "2026-01-08", "Tokyo SoundWave Co.",             "Japan"),
    ("release", "2025-12-04", "Seoul Acoustics Corp.",           "South Korea"),
    ("release", "2026-02-17", "Bangalore Electro Solutions",     "India"),
]


def _inject_historical_cases(case: dict) -> int:
    """Create 4 past closed cases for Case 1 in historical_cases.db so
    the Submit-for-Tax-Review branch of _compute_customs_recommendation
    fires.  Rows fit the same 3-table schema the historical seeder uses.
    """
    init_historical_cases_db()
    conn = _connect(HISTORICAL_CASES_DB)

    rng = random.Random(42)
    inserted = 0

    with conn:
        # Idempotent cleanup — runs ONCE before the insert loop, and
        # deletes ANY row previously tagged with the SOH-DEMO- prefix
        # regardless of (seller, category, destination). This keeps the
        # script cross-run consistent even if we re-point Case 1 to a
        # different parent category (which happened once already when
        # we moved the bone-conduction case from COSMETICS to ELECTRONICS).
        bk_rows = conn.execute(
            "SELECT Sales_Order_Business_Key FROM Sales_Order "
            "WHERE Sales_Order_Business_Key LIKE 'SOH-DEMO-%'"
        ).fetchall()
        for (bk,) in bk_rows:
            conn.execute("DELETE FROM Sales_Order_Case WHERE Sales_Order_Business_Key = ?", (bk,))
            conn.execute("DELETE FROM Sales_Order_Risk WHERE Sales_Order_Business_Key = ?", (bk,))
            conn.execute("DELETE FROM Sales_Order WHERE Sales_Order_Business_Key = ?", (bk,))

        for action, ts_case, hist_seller, hist_origin in _HIST_OUTCOMES:
            case_id = f"CASE-H-DEMO-{uuid.UUID(int=rng.getrandbits(128)).hex[:8].upper()}"
            so_bk   = f"SOH-DEMO-{uuid.UUID(int=rng.getrandbits(128)).hex[:12].upper()}"

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
                    "seller": hist_seller,
                    "origin": hist_origin,
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

    # 1) Delete any prior demo rows in simulation.db so the script is
    # idempotent. Match on the TXDEMO- transaction_id prefix so we sweep
    # every row this script has ever injected — regardless of which
    # parent category / cluster marker a previous run used.
    conn = sqlite3.connect(SIMULATION_DB)
    with conn:
        conn.execute("DELETE FROM transactions WHERE transaction_id LIKE 'TXDEMO-%'")
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
