"""
Historical-case seeder.

Populates data/historical_cases.db with ~30–35 past closed cases
(Country_Destination = 'IE' throughout) spanning Sep 2025 – Mar 2026,
so the C&T frontend's "Previous Cases" panel has realistic reference
data independent of the live simulation in investigation.db.

Distribution design (matches the spec from the project review):

  High-similarity (same seller × declared category as the current
  live IE investigate clusters):  18 cases — mostly Retainment,
  a few Releases, some with Tax feedback. Drives the "retPct > 0.75"
  branch of the Customs / Tax recommended-action rules on the four
  active IE clusters.

  Medium-similarity (same IE-bound sellers, different category or
  different description shape):  8 cases — mix of outcomes.

  Low-similarity (still IE-destined, but unlikely to match the
  current clusters on any dimension):  6 cases — mostly Released,
  used to show "noise" in the history panel.

Each case bundles 1–4 sales orders, with each order carrying a
plausible product description drawn from the same category pool used
by the live seeder. Rates use the Irish canonical rate for the
category; misclassified retained cases have a declared rate below
the expected one.

Run via seed_databases.py (wired in there) or directly:
    python -m lib.historical_seeder
"""
from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.config   import HISTORICAL_CASES_DB
from lib.database import _connect, init_historical_cases_db
from lib          import vat_dataset

_RNG_SEED  = 20260301   # deterministic across runs
_WINDOW    = (datetime(2025, 9, 1,  tzinfo=timezone.utc),
              datetime(2026, 3, 31, tzinfo=timezone.utc))

# Product pools by parent category — reused so descriptions look
# consistent with the live seed. Mirrors the short-phrase pool in
# lib/new_seeder.py but trimmed down for brevity.
_PRODUCT_POOL: dict[str, list[str]] = {
    "ELECTRONICS & ACCESSORIES": [
        "Bluetooth earbuds wireless", "USB-C fast charger", "Smart plug 4-pack",
        "Wireless mouse ergonomic", "HDMI 4K switch", "Phone case magnetic",
        "Portable SSD 1TB",
    ],
    "CLOTHING & TEXTILES": [
        "Cotton t-shirt pack", "Wool sweater knit", "Sports jacket waterproof",
        "Denim slim jeans", "Silk printed scarf",
    ],
    "COSMETICS & PERSONAL CARE": [
        "Vitamin C serum 30ml", "Retinol night cream", "Mineral sunscreen SPF50",
        "Argan oil treatment", "Gentle face wash",
    ],
    "TOYS": [
        "Wooden puzzle set", "Electronic learning kit", "Building block set",
        "Plush teddy bear",
    ],
    "FOOD PRODUCTS": [
        "Dark chocolate bar", "Organic olive oil", "Manuka honey jar",
        "Pasta semolina 500g",
    ],
    "FOOD SUPPLEMENTS & VITAMINS": [
        "Vitamin D3 K2 drops", "Omega-3 fish oil", "Probiotic capsules",
        "Magnesium complex tablets",
    ],
    "BOOKS, PUBLICATIONS & DIGITAL CONTENT": [
        "Children storybook hardcover", "Art history volume", "Cookbook illustrated",
        "Digital reader subscription annual", "Educational textbook pack",
    ],
    "SPORTS & LEISURE / DIGITAL SERVICES": [
        "Yoga mat premium", "Cycling helmet pro", "Running shoes carbon",
        "Sports watch GPS",
    ],
}

# Irish canonical rates used at close time on the historical record.
_CANON_RATE = {
    "ELECTRONICS & ACCESSORIES": 0.23,
    "CLOTHING & TEXTILES":       0.23,
    "COSMETICS & PERSONAL CARE": 0.23,
    "TOYS":                      0.23,
    "FOOD PRODUCTS":             0.0,
    "FOOD SUPPLEMENTS & VITAMINS": 0.23,
    "BOOKS, PUBLICATIONS & DIGITAL CONTENT": 0.0,
    "SPORTS & LEISURE / DIGITAL SERVICES":   0.23,
}

# Current live IE investigate clusters — we generate the
# "high-similarity" block against these exact tuples so the Customs
# retPct > 0.75 rule kicks in on each of them.
_HIGH_SIM_CLUSTERS: list[tuple[str, str]] = [
    ("Mumbai TechTrade Pvt Ltd",    "ELECTRONICS & ACCESSORIES"),
    ("Hyderabad KidsEdu Traders",   "BOOKS, PUBLICATIONS & DIGITAL CONTENT"),
    ("Delhi PharmaExport Pvt Ltd",  "COSMETICS & PERSONAL CARE"),
    ("Bengaluru ActiveGear Ltd",    "CLOTHING & TEXTILES"),
]

# Medium-sim: same 5 IE-bound sellers but rotated into different
# categories than their live cluster. Each seller appears with a
# category from a different "family".
_MEDIUM_SIM: list[tuple[str, str]] = [
    ("Mumbai TechTrade Pvt Ltd",    "SPORTS & LEISURE / DIGITAL SERVICES"),
    ("Hyderabad KidsEdu Traders",   "TOYS"),
    ("Delhi PharmaExport Pvt Ltd",  "FOOD SUPPLEMENTS & VITAMINS"),
    ("Bengaluru ActiveGear Ltd",    "SPORTS & LEISURE / DIGITAL SERVICES"),
    ("Chennai FoodCo Exports",      "FOOD PRODUCTS"),
    ("Chennai FoodCo Exports",      "FOOD SUPPLEMENTS & VITAMINS"),
]

# Low-sim: same sellers but unusual category / low-severity mixes
# that shouldn't light up the current investigate clusters.
_LOW_SIM: list[tuple[str, str]] = [
    ("Mumbai TechTrade Pvt Ltd",    "FOOD PRODUCTS"),
    ("Hyderabad KidsEdu Traders",   "CLOTHING & TEXTILES"),
    ("Delhi PharmaExport Pvt Ltd",  "ELECTRONICS & ACCESSORIES"),
    ("Bengaluru ActiveGear Ltd",    "COSMETICS & PERSONAL CARE"),
    ("Chennai FoodCo Exports",      "BOOKS, PUBLICATIONS & DIGITAL CONTENT"),
    ("Mumbai TechTrade Pvt Ltd",    "TOYS"),
]


def _pick_seller_origin(seller_name: str) -> str:
    s = vat_dataset.seller_by_name(seller_name)
    return s["origin"] if s else "IN"


def _rand_ts(rng: random.Random) -> str:
    span = int((_WINDOW[1] - _WINDOW[0]).total_seconds())
    dt = _WINDOW[0] + timedelta(seconds=rng.randint(0, span))
    return dt.replace(microsecond=0).isoformat()


def _new_case_id(rng: random.Random) -> str:
    return f"CASE-H-{uuid.UUID(int=rng.getrandbits(128)).hex[:10].upper()}"


def _new_so_bk(rng: random.Random) -> str:
    return f"SOH-{uuid.UUID(int=rng.getrandbits(128)).hex[:12].upper()}"


def _choose_outcome(rng: random.Random, preference: str) -> tuple[str, str, str]:
    """Return (Status, Proposed_Action_Customs, Proposed_Action_Tax) for a
    closed case. `preference` biases the draw. Tax action is only filled
    on a minority of cases (tax officer was consulted in the workflow)."""
    pref = {
        "retain_heavy":   [("retain", 0.80), ("release", 0.20)],
        "mixed":          [("retain", 0.45), ("release", 0.55)],
        "release_heavy":  [("retain", 0.10), ("release", 0.90)],
    }[preference]
    draw = rng.random()
    cum = 0.0
    customs_action = "release"
    for action, p in pref:
        cum += p
        if draw <= cum:
            customs_action = action
            break

    # Tax feedback on ~40 % of cases — mirror the customs outcome but
    # keep some divergence to show officer override happened.
    tax_action = ""
    if rng.random() < 0.4:
        if customs_action == "retain":
            tax_action = "risk_confirmed" if rng.random() < 0.75 else "no_limited_risk"
        else:
            tax_action = "no_limited_risk" if rng.random() < 0.75 else "risk_confirmed"

    return "Closed", customs_action, tax_action


def _build_case(rng: random.Random, seller_name: str, parent_cat: str,
                preference: str, description_style: str = "clean") -> dict:
    """Compose one case (+ its 1–4 orders) as inserts for the 3 tables.
    description_style = "clean"  → regular product phrase
                      = "vague"  → generic phrase (feeds a higher
                                   Engine_Description_Vagueness on the case).
    preference        = "retain_heavy" / "mixed" / "release_heavy"."""

    seller        = vat_dataset.seller_by_name(seller_name)
    origin        = seller["origin"] if seller else "IN"
    destination   = "IE"
    pool          = _PRODUCT_POOL.get(parent_cat) or ["imported goods assorted"]
    expected_rate = _CANON_RATE.get(parent_cat, 0.23)

    status, customs_action, tax_action = _choose_outcome(rng, preference)

    # Retained cases tend to have a lower applied rate (misclassified);
    # released cases applied the expected rate.
    applied_rate = expected_rate
    if customs_action == "retain":
        # Step down one canonical tier if possible (23 → 9 → 0), else 0.
        tier_below = {0.23: 0.09, 0.09: 0.0}.get(expected_rate, 0.0)
        applied_rate = tier_below if rng.random() < 0.7 else expected_rate

    n_orders  = rng.randint(1, 4)
    ts_case   = _rand_ts(rng)
    case_id   = _new_case_id(rng)
    so_bk     = _new_so_bk(rng)
    problem   = ("VAT Rate Deviation" if applied_rate < expected_rate
                 else "Risk Pattern")

    # Compose per-order rows. A case's first order's business key is
    # the "primary" one stored on Sales_Order_Case.Sales_Order_Business_Key.
    orders = []
    total_value = 0.0
    for i in range(n_orders):
        item_value   = round(rng.uniform(15.0, 145.0), 2)
        vat_amount   = round(item_value * applied_rate, 2)
        total_value += item_value
        if description_style == "vague" and rng.random() < 0.5:
            phrase = f"Assorted {parent_cat.split()[0].lower()} items"
        else:
            phrase = rng.choice(pool)
        phrase_full = f"{phrase} unit {i + 1:03d}"
        so_bk_i = so_bk if i == 0 else _new_so_bk(rng)
        orders.append({
            "Sales_Order_ID":           f"SO-HIS-{case_id[-6:]}-{i+1:02d}",
            "Sales_Order_Business_Key": so_bk_i,
            "HS_Product_Category":      parent_cat,
            "Product_Description":      phrase_full,
            "Product_Value":            item_value,
            "VAT_Rate":                 applied_rate,
            "VAT_Fee":                  vat_amount,
            "Seller_Name":              seller_name,
            "Country_Origin":           origin,
            "Country_Destination":      destination,
            "Status":                   "Closed",
            "Update_time":              ts_case,
            "Updated_by":               "historical_seed",
            "Case_ID":                  case_id,
        })

    # Case-level engine scores (averaged across orders — we just use
    # representative values). Retained cases carry higher scores.
    if customs_action == "retain":
        overall = round(rng.uniform(0.45, 0.85), 3)
        eng_vat = round(rng.uniform(0.40, 0.75), 3) if applied_rate < expected_rate else 0.0
        eng_ml  = round(rng.uniform(0.20, 0.90), 3)
    else:
        overall = round(rng.uniform(0.10, 0.40), 3)
        eng_vat = 0.0
        eng_ml  = round(rng.uniform(0.00, 0.15), 3)
    eng_vague = round(rng.uniform(0.55, 0.70), 3) if description_style == "vague" else round(rng.uniform(0.02, 0.10), 3)

    level = "High" if overall >= 0.80 else "Medium" if overall >= 1/3 else "Low"

    # Single Sales_Order_Risk row keyed on the primary order's BK.
    risk_row = {
        "Sales_Order_Risk_ID":         f"SOR-HIS-{case_id[-6:]}",
        "Sales_Order_Business_Key":    so_bk,
        "Risk_Type":                   "VAT",
        "Overall_Risk_Score":          overall,
        "Overall_Risk_Level":          level,
        "Seller_Risk_Score":           round(eng_ml * 100, 1),
        "Country_Risk_Score":          0.0,
        "Product_Category_Risk_Score": 0.0,
        "Manufacturer_Risk_Score":     0.0,
        "Confidence_Score":            round(rng.uniform(0.75, 1.0), 3),
        "Overall_Risk_Description":    problem,
        "Proposed_Risk_Action":        "investigate",
        "Risk_Comment":                None,
        "Evaluation_by":               "historical_seed",
        "Update_time":                 ts_case,
        "Updated_by":                  "historical_seed",
    }

    case_row = {
        "Case_ID":                          case_id,
        "Sales_Order_Business_Key":         so_bk,
        "Status":                           status,
        "VAT_Problem_Type":                 problem,
        "Recommended_Product_Value":        None,
        "Recommended_VAT_Product_Category": parent_cat,
        "Recommended_VAT_Rate":             expected_rate,
        "Recommended_VAT_Fee":              round(total_value * expected_rate, 2),
        "AI_Analysis":                      (
            f"Past investigation for {seller_name} on {parent_cat} imports to IE. "
            f"Declared rate {applied_rate*100:.0f}% vs expected {expected_rate*100:.0f}%. "
            f"Outcome: {customs_action}."
        ),
        "AI_Confidence":                    round(rng.uniform(0.6, 0.95), 3),
        "VAT_Gap_Fee":                      round(total_value * (expected_rate - applied_rate), 2),
        "Evaluation_by":                    "Customs Officer",
        "Proposed_Action_Tax":              tax_action or None,
        "Proposed_Action_Customs":          customs_action,
        "Communication":                    "[]",
        "Additional_Evidence":              None,
        "Update_time":                      ts_case,
        "Updated_by":                       "historical_seed",
        "Created_time":                     ts_case,
        "Overall_Case_Risk_Score":          overall,
        "Overall_Case_Risk_Level":          level,
        "Engine_VAT_Ratio":                 eng_vat,
        "Engine_ML_Watchlist":              eng_ml,
        "Engine_IE_Seller_Watchlist":       0.0,
        "Engine_Description_Vagueness":     eng_vague,
    }

    return {"orders": orders, "risk": risk_row, "case": case_row}


def _insert_case(conn, case: dict) -> None:
    for o in case["orders"]:
        conn.execute(
            "INSERT INTO Sales_Order "
            "(Sales_Order_ID, Sales_Order_Business_Key, HS_Product_Category, "
            " Product_Description, Product_Value, VAT_Rate, VAT_Fee, Seller_Name, "
            " Country_Origin, Country_Destination, Status, Update_time, Updated_by, Case_ID) "
            "VALUES "
            "(:Sales_Order_ID, :Sales_Order_Business_Key, :HS_Product_Category, "
            " :Product_Description, :Product_Value, :VAT_Rate, :VAT_Fee, :Seller_Name, "
            " :Country_Origin, :Country_Destination, :Status, :Update_time, :Updated_by, :Case_ID)",
            o,
        )
    conn.execute(
        "INSERT INTO Sales_Order_Risk "
        "(Sales_Order_Risk_ID, Sales_Order_Business_Key, Risk_Type, Overall_Risk_Score, "
        " Overall_Risk_Level, Seller_Risk_Score, Country_Risk_Score, Product_Category_Risk_Score, "
        " Manufacturer_Risk_Score, Confidence_Score, Overall_Risk_Description, Proposed_Risk_Action, "
        " Risk_Comment, Evaluation_by, Update_time, Updated_by) "
        "VALUES "
        "(:Sales_Order_Risk_ID, :Sales_Order_Business_Key, :Risk_Type, :Overall_Risk_Score, "
        " :Overall_Risk_Level, :Seller_Risk_Score, :Country_Risk_Score, :Product_Category_Risk_Score, "
        " :Manufacturer_Risk_Score, :Confidence_Score, :Overall_Risk_Description, :Proposed_Risk_Action, "
        " :Risk_Comment, :Evaluation_by, :Update_time, :Updated_by)",
        case["risk"],
    )
    conn.execute(
        "INSERT INTO Sales_Order_Case ("
        " Case_ID, Sales_Order_Business_Key, Status, VAT_Problem_Type, "
        " Recommended_Product_Value, Recommended_VAT_Product_Category, "
        " Recommended_VAT_Rate, Recommended_VAT_Fee, AI_Analysis, AI_Confidence, "
        " VAT_Gap_Fee, Evaluation_by, Proposed_Action_Tax, Proposed_Action_Customs, "
        " Communication, Additional_Evidence, Update_time, Updated_by, Created_time, "
        " Overall_Case_Risk_Score, Overall_Case_Risk_Level, Engine_VAT_Ratio, "
        " Engine_ML_Watchlist, Engine_IE_Seller_Watchlist, Engine_Description_Vagueness) "
        "VALUES ("
        " :Case_ID, :Sales_Order_Business_Key, :Status, :VAT_Problem_Type, "
        " :Recommended_Product_Value, :Recommended_VAT_Product_Category, "
        " :Recommended_VAT_Rate, :Recommended_VAT_Fee, :AI_Analysis, :AI_Confidence, "
        " :VAT_Gap_Fee, :Evaluation_by, :Proposed_Action_Tax, :Proposed_Action_Customs, "
        " :Communication, :Additional_Evidence, :Update_time, :Updated_by, :Created_time, "
        " :Overall_Case_Risk_Score, :Overall_Case_Risk_Level, :Engine_VAT_Ratio, "
        " :Engine_ML_Watchlist, :Engine_IE_Seller_Watchlist, :Engine_Description_Vagueness)",
        case["case"],
    )


def seed_historical_cases_db() -> int:
    """Wipe historical_cases.db and repopulate with a curated set of
    past closed IE cases. Returns total cases inserted."""
    init_historical_cases_db()
    rng = random.Random(_RNG_SEED)

    conn = _connect(HISTORICAL_CASES_DB)
    with conn:
        conn.execute("DELETE FROM Sales_Order_Case")
        conn.execute("DELETE FROM Sales_Order_Risk")
        conn.execute("DELETE FROM Sales_Order")
    conn.close()

    cases: list[dict] = []

    # ── High-similarity: 4 clusters × ~4–5 cases each, retainment-heavy ─
    for seller, cat in _HIGH_SIM_CLUSTERS:
        for _ in range(rng.randint(4, 5)):
            # 1-in-5 gets a vague description to diversify the vagueness
            # signal on these historical cases.
            style = "vague" if rng.random() < 0.2 else "clean"
            cases.append(_build_case(rng, seller, cat, "retain_heavy", style))

    # ── Medium-similarity: mix outcomes ────────────────────────────────
    for seller, cat in _MEDIUM_SIM:
        cases.append(_build_case(rng, seller, cat, "mixed",
                                 "vague" if rng.random() < 0.15 else "clean"))

    # ── Low-similarity: release-heavy, cosmetic presence in history ────
    for seller, cat in _LOW_SIM:
        cases.append(_build_case(rng, seller, cat, "release_heavy", "clean"))

    rng.shuffle(cases)

    conn = _connect(HISTORICAL_CASES_DB)
    with conn:
        for c in cases:
            _insert_case(conn, c)
    conn.close()

    # Summary
    from collections import Counter
    by_cluster = Counter((c["orders"][0]["Seller_Name"], c["orders"][0]["HS_Product_Category"]) for c in cases)
    by_action  = Counter(c["case"]["Proposed_Action_Customs"] for c in cases)
    print(f"  {len(cases)} historical cases written")
    print(f"  outcomes: {dict(by_action)}")
    print(f"  top 5 (seller, cat) clusters:")
    for (s, cat), n in by_cluster.most_common(5):
        print(f"    {n}× {s[:24]:<24} / {cat}")

    return len(cases)


if __name__ == "__main__":
    n = seed_historical_cases_db()
    print(f"\n✓ {n} historical cases in {HISTORICAL_CASES_DB}")
