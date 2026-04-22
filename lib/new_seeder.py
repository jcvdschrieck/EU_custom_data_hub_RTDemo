"""
New-dataset seeder for simulation.db.

Reads VAT_Cases_Generated_17042026_6.xlsx (191 source rows) and
Context/Fake_ML.xlsx (per-tx engine outputs), emits transactions into
simulation.db with the new pre-baked engine fields populated.

Pipeline:

  1. Load both xlsx files; index Fake_ML by xlsx_row_index.
  2. For each (seller, dest, parent_category) cluster of investigate-
     route xlsx rows, pick a target cluster size (1..15, median 5)
     and synthesize siblings to reach it. Siblings inherit the
     parent's declared+recommended categories and engine outputs.
  3. Rewrite each cluster's product descriptions to share a common
     6-word prefix so Jaccard >= 0.4 between any pair.
  4. Release/retain rows pass through unchanged (no clustering, no
     synthetic siblings — neither route forms cases at the C&T factory).
  5. Distribute timestamps uniformly across the SIM_START..SIM_END
     window (default 15 minutes starting 2026-04-01 00:00:00).
  6. Generate a fresh transaction_id and value (uniform [10, 150)) for
     every tx — both xlsx-derived and synthetic.
  7. Bulk-insert into simulation.db.

Run via scripts/seed_new_dataset.py (preferred) or
seed_databases.py (which now wires this module in for the sim DB).
"""
from __future__ import annotations

import random
import uuid
from datetime import timedelta
from pathlib import Path

import pandas as pd

from lib.config      import SIM_START_DT, SIM_END_DT, SIMULATION_DB
from lib.database    import bulk_insert, init_simulation_db, _connect
from lib             import vat_dataset

ROOT      = Path(__file__).resolve().parent.parent
SOURCE_XLSX = ROOT / "Context" / "VAT_Cases_Generated_17042026_6.xlsx"
FAKE_ML_XLSX = ROOT / "Context" / "Fake_ML.xlsx"

# Seed for reproducibility — change only when intentionally regenerating.
_RNG_SEED = 20260401

# Value distribution: uniform [10, 150). Below the EU IOSS threshold (€150).
_VALUE_MIN = 10.0
_VALUE_MAX = 150.0

# ── Amplification strategy ─────────────────────────────────────────────────
# Each xlsx source row spawns N transactions in simulation.db: the xlsx row
# itself + (N-1) synthetic children that inherit the row's declared/
# recommended VAT categories and pre-baked engine outputs verbatim. The
# child ONLY differs in transaction_id, timestamp, value, and description.
#
# Factors tuned so:
#   - Total tx ≈ 2000.
#   - Route proportions preserve the xlsx split (~79% release, ~17%
#     investigate, ~4% retain).
#   - Ireland-destined volume is a minority of the total (≈13%) but
#     Ireland investigate clusters are amplified to ~30 tx each so the
#     C&T frontend (which filters to Country_Destination == "IE") shows
#     rich, multi-order cases.
#
# ("target_cluster_size", N) for investigate rows scales the whole
# cluster — siblings are shared across the cluster's xlsx rows. For
# release/retain (no clustering) the factor is per-row.
_INVESTIGATE_CLUSTER_SIZE = {
    "IE":     30,   # 4 clusters × 30 ≈ 120 tx
    "non-IE": 14,   # 15 clusters × 14 ≈ 210 tx
}
_RELEASE_COPIES_PER_ROW = {
    "IE":     4,    # 35 rows × 4 = 140
    "non-IE": 12,   # 116 rows × 12 = 1392
}
_RETAIN_COPIES_PER_ROW  = {
    "IE":     12,   # (no IE retain rows in xlsx, kept for symmetry)
    "non-IE": 12,   # 8 rows × 12 = 96
}


def _dest_tier(destination: str) -> str:
    return "IE" if destination == "IE" else "non-IE"


# ── Description rewriter ────────────────────────────────────────────────────

def _seller_code(seller_name: str) -> str:
    """First three letters of each capitalised word, joined."""
    parts = [w[:3].upper() for w in seller_name.split() if w[0].isupper()]
    return "".join(parts[:2]) or "GEN"


def _category_code(parent_category: str) -> str:
    """Two-letter prefix derived from the parent category."""
    return "".join(w[0].upper() for w in parent_category.split() if w[0].isalpha())[:3]


_PRODUCT_POOL: dict[str, list[str]] = {
    "ELECTRONICS & ACCESSORIES": [
        "Bluetooth wireless earbuds",
        "USB-C charging hub",
        "Laptop stand aluminium",
        "Phone charging case",
        "Smart plug WiFi",
        "Mechanical keyboard RGB",
        "4K webcam HDR",
        "Wireless mouse ergonomic",
        "Monitor stand dual-arm",
        "HDMI switch 4-port",
        "Smart home speaker",
        "LED desk lamp",
    ],
    "CLOTHING & TEXTILES": [
        "Cotton crew-neck shirt",
        "Wool winter coat",
        "Denim slim jeans",
        "Silk printed scarf",
        "Leather handbag classic",
        "Linen summer dress",
        "Sports jacket waterproof",
        "Cashmere sweater knit",
    ],
    "COSMETICS & PERSONAL CARE": [
        "Vitamin C serum",
        "Retinol night cream",
        "Mineral sunscreen SPF50",
        "Argan oil treatment",
        "Brightening face mask",
        "Gentle face wash",
        "Body butter shea",
        "Eau de parfum",
    ],
    "TOYS": [
        "Electronic learning kit",
        "Wooden puzzle set",
        "Outdoor play cones",
        "Plush bear stuffed",
        "Craft hobby kit",
        "Educational flashcards pack",
        "Building block set",
        "Costume dress-up",
    ],
    "FOOD PRODUCTS": [
        "Dark chocolate bar",
        "Cereal breakfast box",
        "Organic olive oil",
        "Dried pasta semolina",
        "Manuka honey jar",
        "Pet food kibble",
        "Confectionery gift box",
    ],
    "FOOD SUPPLEMENTS & VITAMINS": [
        "Vitamin D3 K2",
        "Omega-3 fish oil",
        "Magnesium complex tablets",
        "Probiotic capsules strain",
        "Protein powder whey",
        "Ashwagandha root extract",
        "Collagen peptides drink",
    ],
    "BOOKS, PUBLICATIONS & DIGITAL CONTENT": [
        "Educational textbook pack",
        "Digital reader subscription",
        "Art history volume",
        "Cookbook recipes illustrated",
        "Children storybook classic",
    ],
    "SPORTS & LEISURE / DIGITAL SERVICES": [
        "Cycling helmet pro",
        "Running shoes carbon",
        "Yoga mat premium",
        "Sports watch GPS",
    ],
}


def _cluster_markers(seller_name: str, destination: str, parent_category: str) -> str:
    """6 cluster-tagged tokens — the Jaccard anchor.

    Each token embeds a cluster id (SELLER-DEST-CAT) so the tokens are
    unique across clusters: cross-cluster Jaccard stays near zero
    regardless of how many clusters share destination or category.
    Within a cluster all 6 tokens are identical, which keeps intra-
    cluster Jaccard around 0.5 even when product phrases and unit
    numbers differ between siblings.
    """
    cid = f"{_seller_code(seller_name)}-{destination}-{_category_code(parent_category)}"
    return (
        f"lot-{cid} ref-{cid} shipment-{cid} "
        f"batch-{cid} manifest-{cid} series-{cid}"
    )


def _pick_product_phrase(rng: random.Random, parent_category: str,
                         member_idx: int) -> str:
    """Choose a realistic product phrase for this transaction.

    Rotates deterministically through the category pool by
    member_idx so adjacent tx in a cluster get different phrases,
    then adds a small random jitter offset for variety across runs.
    """
    pool = _PRODUCT_POOL.get(parent_category) or ["imported goods assorted"]
    jitter = rng.randrange(len(pool))
    return pool[(member_idx + jitter) % len(pool)]


# ── Seeding ─────────────────────────────────────────────────────────────────

def _route_from_action(action: str) -> str:
    return (action or "").strip().lower()


def _new_tx_id(rng: random.Random) -> str:
    return f"TX-{uuid.UUID(int=rng.getrandbits(128)).hex[:12].upper()}"


def _jitter_vagueness(rng: random.Random, pre_baked: float) -> float:
    """Return a per-tx vagueness score that looks like the output of an
    actual embedding-model cosine similarity rather than the xlsx's
    binary 0 / 0.60 pre-bake.

    The xlsx encodes Score 2 as Yes (60) or No (0). Copying that
    verbatim produces exactly 0.000 for every non-vague tx, which
    officers find odd on a UI that advertises a 0..1 continuous
    score. In reality a MiniLM embedding comparison to generic
    anchor phrases never hits zero — there is always a small
    baseline similarity for any English product description.

    We keep the routing behaviour unchanged by staying well below
    the 0.5 flag threshold when the pre-bake is 0, and above it
    when the pre-bake fires.
    """
    # Jitter bounds are tuned to preserve the xlsx route distribution
    # (79% / 17% / 4%). With engine weight 0.8, a max baseline of 0.08
    # contributes at most 0.064 to the consolidated score — small
    # enough that no borderline tx flips across the 1/3 or 0.8
    # routing thresholds.
    if pre_baked <= 0.0:
        return round(rng.uniform(0.02, 0.08), 3)   # quiet baseline, never 0 exactly
    if pre_baked >= 0.5:
        return round(pre_baked + rng.uniform(-0.03, 0.05), 3)   # band around firing value
    return round(pre_baked + rng.uniform(-0.02, 0.02), 3)       # band around mid-range


def _build_tx_row(
    *,
    rng: random.Random,
    timestamp_iso: str,
    seller_dict: dict,
    destination: str,
    parent_category: str,
    declared_subcat: str,
    declared_rate: float,
    recommended_rate: float,
    description: str,
    fake_ml_row: dict,
) -> dict:
    """Compose one row in the shape expected by lib.database.bulk_insert."""
    seller_name    = seller_dict["name"]
    seller_origin  = seller_dict["origin"]
    value          = round(rng.uniform(_VALUE_MIN, _VALUE_MAX), 2)
    vat_amount     = round(value * declared_rate, 2)

    return {
        "transaction_id":   _new_tx_id(rng),
        "transaction_date": timestamp_iso,
        "seller_id":        seller_dict["id"],
        "seller_name":      seller_name,
        "seller_country":   seller_origin,
        "item_description": description,
        "item_category":    parent_category,
        "value":            value,
        "vat_rate":         declared_rate,
        "vat_amount":       vat_amount,
        "buyer_country":    destination,
        "correct_vat_rate": recommended_rate,
        # Has-error semantics: any rate mismatch on the declared invoice.
        "has_error":        1 if abs(declared_rate - recommended_rate) > 1e-9 else 0,
        "xml_message":      None,
        "created_at":       timestamp_iso,
        # No producer (the new dataset's "seller" is the non-EU
        # manufacturer directly — no two-tier party split).
        "producer_id":      None,
        "producer_name":    None,
        "producer_country": None,
        "producer_city":    None,
        # New-dataset Stage-3 fields ─────────────────────────────────
        "vat_subcategory_code":               declared_subcat,
        "engine_vat_ratio_risk":              float(fake_ml_row["expected_vat_ratio_risk"]),
        "engine_ml_risk":                     float(fake_ml_row["expected_ml_risk"]),
        "engine_ml_seller_contribution":      float(fake_ml_row["seller_contribution"]),
        "engine_ml_origin_contribution":      float(fake_ml_row["country_origin_contribution"]),
        "engine_ml_category_contribution":    float(fake_ml_row["category_contribution"]),
        "engine_ml_destination_contribution": float(fake_ml_row["destination_contribution"]),
        "engine_vagueness_risk":              _jitter_vagueness(rng, float(fake_ml_row["expected_vagueness_risk"])),
        # IE watchlist is currently empty in the dataset; pre-bake 0
        # (the engine treats both 0 and missing-pre-bake as "not flagged"
        # but having an explicit value keeps the engine on the pre-baked
        # path rather than the legacy IE_WATCHLIST set lookup).
        "engine_ie_watchlist_risk":           0.0,
    }


def _evenly_spaced_timestamps(n: int, rng: random.Random) -> list[str]:
    """n timestamps inside [SIM_START_DT, SIM_END_DT). Evenly spaced with
    small jitter so we don't collide on identical sim-time instants but
    still fan out across the whole window."""
    if n <= 0:
        return []
    window_seconds = (SIM_END_DT - SIM_START_DT).total_seconds()
    step = window_seconds / (n + 1)   # leave a margin at start+end
    out: list[str] = []
    for i in range(n):
        base   = step * (i + 1)
        jitter = rng.uniform(-step * 0.25, step * 0.25)
        offset = max(0.5, min(window_seconds - 0.5, base + jitter))
        ts = SIM_START_DT + timedelta(seconds=offset)
        out.append(ts.isoformat())
    return out


def seed_simulation_db_from_xlsx() -> int:
    """Wipe simulation.db and reseed it from the xlsx + Fake_ML reference.

    Returns the number of transactions inserted.
    """
    init_simulation_db()
    rng = random.Random(_RNG_SEED)

    src = pd.read_excel(SOURCE_XLSX, sheet_name="VAT Missclassification Last")
    fml = pd.read_excel(FAKE_ML_XLSX, sheet_name="Per-Tx Expected Engine Outputs")
    fml_by_idx = {int(r["xlsx_row_index"]): r.to_dict() for _, r in fml.iterrows()}

    # Pre-resolve sellers by name to spare per-row lookups.
    seller_by_name = {s["name"]: s for s in vat_dataset.SELLERS}

    rows: list[dict] = []

    # ── Pass 1: investigate clusters (xlsx rows + amplified siblings) ───────
    investigate_mask = src["Customs Authority Action (Calculated)"].str.lower() == "investigate"
    investigate_rows = src[investigate_mask]

    cluster_groups = investigate_rows.groupby(
        ["Seller", "Destination Country", "VAT Category (declared)"], sort=True
    )

    cluster_summary: list[tuple[str, str, str, int, int]] = []

    for (seller_name, destination, parent_cat), group in cluster_groups:
        seller_dict = seller_by_name[seller_name]
        target_size = _INVESTIGATE_CLUSTER_SIZE[_dest_tier(destination)]
        target_size = max(len(group), target_size)
        markers     = _cluster_markers(seller_name, destination, parent_cat)

        xlsx_records = [
            {"orig_idx": int(idx), "data": row.to_dict()}
            for idx, row in group.iterrows()
        ]
        siblings_needed = target_size - len(xlsx_records)
        cluster_summary.append((seller_name, destination, parent_cat,
                                len(xlsx_records), target_size))

        cluster_members = [(rec, 0) for rec in xlsx_records] + [
            (xlsx_records[sibling_idx % len(xlsx_records)], sibling_idx + 1)
            for sibling_idx in range(siblings_needed)
        ]

        for member_idx, (rec, sibling_idx) in enumerate(cluster_members):
            xrow     = rec["data"]
            orig_idx = rec["orig_idx"]
            phrase   = _pick_product_phrase(rng, parent_cat, member_idx)
            description = f"{phrase} unit {member_idx + 1:03d} — {markers}"

            row = _build_tx_row(
                rng=rng,
                timestamp_iso="",
                seller_dict=seller_dict,
                destination=destination,
                parent_category=parent_cat,
                declared_subcat=xrow["VAT Code (declared)"],
                declared_rate=float(xrow["VAT Rate (%)"]) / 100.0,
                recommended_rate=float(xrow["VAT Rate (Recommended)"]) / 100.0,
                description=description,
                fake_ml_row=fml_by_idx[orig_idx],
            )
            rows.append(row)

    # ── Pass 2: release + retain rows (per-row amplification, no clusters) ──
    # Release and retain tx bypass the C&T factory, so they do not need
    # cluster-friendly descriptions. Each xlsx row spawns N copies, each
    # with a fresh tx_id / timestamp / value / description (the copies
    # otherwise inherit the xlsx row's declared & recommended categories
    # and pre-baked engine outputs verbatim).
    route_by_label = {"release": _RELEASE_COPIES_PER_ROW,
                      "retain":  _RETAIN_COPIES_PER_ROW}
    other_rows = src[~investigate_mask]
    for orig_idx, xrow in other_rows.iterrows():
        route       = _route_from_action(xrow["Customs Authority Action (Calculated)"])
        copies      = route_by_label[route][_dest_tier(xrow["Destination Country"])]
        seller_dict = seller_by_name[xrow["Seller"]]
        base_desc   = str(xrow["Product Description (declared)"])

        for copy_idx in range(copies):
            description = (
                base_desc if copy_idx == 0
                else f"{base_desc} — lot {copy_idx + 1:03d}"
            )
            row = _build_tx_row(
                rng=rng,
                timestamp_iso="",
                seller_dict=seller_dict,
                destination=xrow["Destination Country"],
                parent_category=xrow["VAT Category (declared)"],
                declared_subcat=xrow["VAT Code (declared)"],
                declared_rate=float(xrow["VAT Rate (%)"]) / 100.0,
                recommended_rate=float(xrow["VAT Rate (Recommended)"]) / 100.0,
                description=description,
                fake_ml_row=fml_by_idx[int(orig_idx)],
            )
            rows.append(row)

    # ── Pass 3: assign timestamps inside the sim window ─────────────────────
    timestamps = _evenly_spaced_timestamps(len(rows), rng)
    rng.shuffle(rows)   # randomise arrival order so investigate clusters interleave with releases
    for r, ts in zip(rows, timestamps):
        r["transaction_date"] = ts
        r["created_at"]       = ts

    # ── Pass 4: wipe simulation.db transactions and bulk-insert ─────────────
    conn = _connect(SIMULATION_DB)
    with conn:
        conn.execute("DELETE FROM transactions")
    conn.close()
    bulk_insert(rows, path=SIMULATION_DB)

    # Report
    from collections import Counter
    by_dest  = Counter(r["buyer_country"] for r in rows)
    ie_count    = by_dest.get("IE", 0)
    non_ie_count = sum(n for d, n in by_dest.items() if d != "IE")

    print(f"  source xlsx rows:              {len(src)}")
    print(f"  investigate clusters:          {len(cluster_summary)}")
    sizes = [s[4] for s in cluster_summary]
    print(f"  → cluster sizes (min/median/max): {min(sizes)}/{sorted(sizes)[len(sizes)//2]}/{max(sizes)}")
    print(f"  total tx written:              {len(rows)}")
    print(f"  by destination:                IE={ie_count} ({ie_count/len(rows):.1%})  "
          f"non-IE={non_ie_count} ({non_ie_count/len(rows):.1%})")
    print(f"    {dict(by_dest)}")
    return len(rows)


if __name__ == "__main__":
    n = seed_simulation_db_from_xlsx()
    print(f"\n✓ {n} transactions written to {SIMULATION_DB}")
