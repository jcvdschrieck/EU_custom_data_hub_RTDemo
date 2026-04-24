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
#   - Route proportions preserve the xlsx split (~79% release, ~17%
#     investigate, ~4% retain).
#   - Ireland-destined IE investigate clusters are amplified to a
#     randomized target size in [50, 100] so the C&T frontend (which
#     filters to Country_Destination == "IE") shows rich cases carrying
#     up to 100 orders each.
#   - non-IE clusters stay small (they don't drive the C&T demo).
#
# Investigate cluster size is sampled per-cluster from an inclusive range
# (min, max). All members of a cluster share identical cluster markers, so
# Jaccard stays > DESCRIPTION_SIMILARITY_THRESHOLD regardless of size and
# find_similar_open_case merges them into a single open case.
_INVESTIGATE_CLUSTER_SIZE: dict[str, tuple[int, int]] = {
    "IE":     (50, 100),   # 4 clusters × ~75 ≈ 300 tx
    "non-IE": (14, 14),    # 15 clusters × 14 ≈ 210 tx
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


_GENERIC_POOL: dict[str, list[str]] = {
    # Deliberately vague phrases used for a minority of cluster siblings
    # so each case carries a mix of specific and generic descriptions.
    # Jaccard anchoring is still carried by the six cluster-tagged
    # markers appended to the description, not by these phrases.
    "ELECTRONICS & ACCESSORIES":            ["Miscellaneous electronics goods"],
    "CLOTHING & TEXTILES":                  ["Assorted clothing items"],
    "COSMETICS & PERSONAL CARE":            ["Mixed cosmetics products"],
    "TOYS":                                 ["Various toys assorted"],
    "FOOD PRODUCTS":                        ["Assorted food items"],
    "FOOD SUPPLEMENTS & VITAMINS":          ["Mixed supplement products"],
    "BOOKS, PUBLICATIONS & DIGITAL CONTENT":["Assorted publications stock"],
    "SPORTS & LEISURE / DIGITAL SERVICES":  ["Mixed sports leisure items"],
}


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


def _cluster_markers(seller_name: str, destination: str, parent_category: str,
                     suffix: str = "") -> str:
    """6 cluster-tagged tokens — the Jaccard anchor.

    Each token embeds a cluster id (SELLER-DEST-CAT[+SUFFIX]) so the
    tokens are unique across clusters: cross-cluster Jaccard stays near
    zero regardless of how many clusters share destination or category.
    Within a cluster all 6 tokens are identical, which keeps intra-
    cluster Jaccard around 0.5 even when product phrases and unit
    numbers differ between siblings.

    The optional *suffix* lets a single (seller, dest, cat) tuple be
    split into two disjoint sub-clusters — they share all 3 routing
    fields (so they correlate in the C&T Risk Management System) but
    carry non-overlapping markers and product phrases so the Jaccard
    threshold keeps them as separate open cases.
    """
    cid = f"{_seller_code(seller_name)}-{destination}-{_category_code(parent_category)}"
    if suffix:
        cid = f"{cid}-{suffix}"
    return (
        f"lot-{cid} ref-{cid} shipment-{cid} "
        f"batch-{cid} manifest-{cid} series-{cid}"
    )


# Live (seller, destination, declared parent category) tuples that get
# split into two separate open cases so the C&T frontend's correlate
# panel has siblings to show. Each split tuple emits its cluster members
# across two sub-clusters with disjoint markers + disjoint product pool
# halves — Jaccard stays below DESCRIPTION_SIMILARITY_THRESHOLD between
# sub-clusters, so find_similar_open_case does NOT merge them.
_CORRELATE_SPLITS: set[tuple[str, str, str]] = {
    ("Mumbai TechTrade Pvt Ltd", "IE", "ELECTRONICS & ACCESSORIES"),
    ("Bengaluru ActiveGear Ltd", "IE", "CLOTHING & TEXTILES"),
}


def _pick_product_phrase(rng: random.Random, parent_category: str,
                         member_idx: int,
                         pool_override: list[str] | None = None) -> str:
    """Choose a realistic product phrase for this transaction.

    Rotates deterministically through the category pool by
    member_idx so adjacent tx in a cluster get different phrases,
    then adds a small random jitter offset for variety across runs.

    When *pool_override* is provided (split sub-clusters), phrases are
    drawn only from that subset so each sub-cluster has a disjoint
    product vocabulary.
    """
    pool = pool_override or _PRODUCT_POOL.get(parent_category) or ["imported goods assorted"]
    jitter = rng.randrange(len(pool))
    return pool[(member_idx + jitter) % len(pool)]


def _pick_generic_phrase(rng: random.Random, parent_category: str) -> str:
    """Return a deliberately generic product phrase for 'vague variant'
    tx. These sit alongside the specific product tx in the same case,
    giving officers a mix of specific and vague descriptions to review.
    """
    pool = _GENERIC_POOL.get(parent_category) or ["Mixed imported goods"]
    return rng.choice(pool)


# Within each investigate cluster a configurable fraction of siblings are
# converted to "vague variants": generic description, high vagueness score,
# low VAT and ML signals. They stay in the investigate route (per-tx score
# ~0.4–0.6) so they remain visible in the case rather than flipping to
# retain.
_VAGUE_VARIANT_FRACTION_MIN = 0.15
_VAGUE_VARIANT_FRACTION_MAX = 0.25


# ── Seeding ─────────────────────────────────────────────────────────────────

def _route_from_action(action: str) -> str:
    return (action or "").strip().lower()


def _new_tx_id(rng: random.Random) -> str:
    return f"TX-{uuid.UUID(int=rng.getrandbits(128)).hex[:12].upper()}"


def _jitter_ml_once(rng: random.Random, pre_baked: float) -> float:
    """Jitter the xlsx ML score (Score 3 / 100) to a continuous value.

    ML risk is a function of (seller, origin, category, destination) —
    all four fields are identical for every tx in a cluster. So the
    jittered value is applied ONCE per xlsx parent row, not per tx;
    every sibling inheriting from the same parent inherits the same
    ML reading. Within-case variability on ML stays near zero, which
    matches the ML model's actual behaviour.

    Keeps the same buckets as the xlsx (0 / 0.40 / 0.90), just nudged
    off the hard values so the UI doesn't show suspicious round
    numbers like 0.00 or 0.40.
    """
    if pre_baked <= 0.0:
        return round(rng.uniform(0.03, 0.10), 3)
    if pre_baked >= 0.8:
        return round(pre_baked + rng.uniform(-0.04, 0.06), 3)
    # Mid bucket around 0.40
    return round(pre_baked + rng.uniform(-0.05, 0.05), 3)


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
    value: float | None = None,
) -> dict:
    """Compose one row in the shape expected by lib.database.bulk_insert.

    *value* lets the caller force a per-tx amount — used by the investigate
    pass to keep every sibling in a cluster within ±25% of a cluster-level
    base price so every order inside a case has a comparable value. When
    None, a free uniform draw is used (release/retain rows, no clustering).
    """
    seller_name    = seller_dict["name"]
    seller_origin  = seller_dict["origin"]
    if value is None:
        value = round(rng.uniform(_VALUE_MIN, _VALUE_MAX), 2)
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

    # Apply ML jitter once per xlsx row so every sibling of a given
    # parent carries the SAME ML reading. ML is a function of (seller,
    # origin, category, destination), so within-cluster variability is
    # zero by construction.
    for rec in fml_by_idx.values():
        rec["expected_ml_risk"] = _jitter_ml_once(rng, float(rec["expected_ml_risk"]))

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
        size_lo, size_hi = _INVESTIGATE_CLUSTER_SIZE[_dest_tier(destination)]
        target_size = rng.randint(size_lo, size_hi)
        target_size = max(len(group), target_size)

        xlsx_records = [
            {"orig_idx": int(idx), "data": row.to_dict()}
            for idx, row in group.iterrows()
        ]
        siblings_needed = target_size - len(xlsx_records)
        cluster_summary.append((seller_name, destination, parent_cat,
                                len(xlsx_records), target_size))

        all_members = [(rec, 0) for rec in xlsx_records] + [
            (xlsx_records[sibling_idx % len(xlsx_records)], sibling_idx + 1)
            for sibling_idx in range(siblings_needed)
        ]

        # Split designated live tuples into two sub-clusters so the
        # correlate panel has siblings to show. Each sub-cluster is a
        # full-size cluster (same target_size as a normal cluster), so
        # the split doubles the transactions for that tuple instead of
        # halving per-case mass. Sub A inherits the xlsx records;
        # sub B is fully synthetic siblings to avoid double-emitting
        # xlsx data.
        split_tuple = (seller_name, destination, parent_cat) in _CORRELATE_SPLITS
        if split_tuple:
            pool = _PRODUCT_POOL.get(parent_cat) or ["imported goods assorted"]
            half = max(1, len(pool) // 2)
            members_B = [
                (xlsx_records[sibling_idx % len(xlsx_records)], sibling_idx + 1)
                for sibling_idx in range(target_size)
            ]
            sub_clusters = [
                ("A", pool[:half],
                 _cluster_markers(seller_name, destination, parent_cat, suffix="A"),
                 all_members),
                ("B", pool[half:],
                 _cluster_markers(seller_name, destination, parent_cat, suffix="B"),
                 members_B),
            ]
        else:
            sub_clusters = [
                ("", None,
                 _cluster_markers(seller_name, destination, parent_cat),
                 all_members),
            ]

        for sub_tag, pool_override, markers, cluster_members in sub_clusters:
            # Pick the subset of synthetic siblings that will be rendered
            # as "vague variants" — computed per sub-cluster.
            sibling_positions = [
                i for i, (_, s_idx) in enumerate(cluster_members) if s_idx > 0
            ]
            fraction = rng.uniform(_VAGUE_VARIANT_FRACTION_MIN, _VAGUE_VARIANT_FRACTION_MAX)
            vague_count = int(round(len(sibling_positions) * fraction))
            vague_positions = (set(rng.sample(sibling_positions, vague_count))
                               if vague_count else set())

            # Cluster-level base price so any two orders inside the
            # resulting case differ by at most 25%. Window width is
            # [base/√1.25, base·√1.25] ≈ [base·0.894, base·1.118] so the
            # max-to-min ratio for any pair stays ≤ 1.25. Base is picked
            # so the full window stays inside [_VALUE_MIN, _VALUE_MAX].
            cluster_base_value = rng.uniform(_VALUE_MIN / 0.894, _VALUE_MAX / 1.118)

            for member_idx, (rec, sibling_idx) in enumerate(cluster_members):
                xrow     = rec["data"]
                orig_idx = rec["orig_idx"]
                is_vague_variant = member_idx in vague_positions

                if is_vague_variant:
                    phrase = _pick_generic_phrase(rng, parent_cat)
                else:
                    phrase = _pick_product_phrase(rng, parent_cat, member_idx,
                                                  pool_override=pool_override)
                description = f"{phrase} unit {member_idx + 1:03d} — {markers}"

                tx_value = round(
                    min(
                        rng.uniform(cluster_base_value * 0.894, cluster_base_value * 1.118),
                        _VALUE_MAX - 0.01,
                    ),
                    2,
                )

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
                    value=tx_value,
                )
                if is_vague_variant:
                    # Vague variants carry a clean invoice (no rate issue, no
                    # supplier risk) but a high vagueness score. Their per-tx
                    # score lands around 0.45–0.55 — investigate, never retain.
                    row["engine_vat_ratio_risk"]              = 0.0
                    row["engine_ml_risk"]                     = round(rng.uniform(0.0, 0.05), 3)
                    row["engine_ml_seller_contribution"]      = 0.0
                    row["engine_ml_origin_contribution"]      = 0.0
                    row["engine_ml_category_contribution"]    = 0.0
                    row["engine_ml_destination_contribution"] = 0.0
                    row["engine_vagueness_risk"]              = round(rng.uniform(0.55, 0.70), 3)
                    # Rate and category still match the cluster (declared
                    # matches recommended, since this variant is "just" vague).
                    row["vat_rate"]         = row["correct_vat_rate"]
                    row["vat_amount"]       = round(row["value"] * row["vat_rate"], 2)
                    row["has_error"]        = 0
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
