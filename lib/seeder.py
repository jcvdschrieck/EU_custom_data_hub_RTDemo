"""
Seed both databases.

Historical (European Custom DB): 2025-09-01 → 2026-02-28
Simulation (Simulation DB):      2026-03-01 → 2026-03-31

Both use the same generation logic. ~50 transactions per day,
distributed with realistic intra-day patterns (busier 09:00-20:00).
~10 % of transactions carry a VAT rate error.
"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, timedelta, timezone

from lib.catalog import COUNTRIES, SUPPLIERS, VAT_RATES
from lib.config import (
    EUROPEAN_CUSTOM_DB, SIMULATION_DB,
    SIM_START_DT, SIM_END_DT,
)
from lib.database import (
    bulk_insert,
    init_european_custom_db,
    init_simulation_db,
)
from lib.xml_generator import transaction_to_xml

random.seed(42)

# Weights per hour (0-23) — mimics e-commerce traffic peaks
_HOUR_WEIGHTS = [
    0.5, 0.3, 0.2, 0.2, 0.2, 0.3,   # 00-05
    0.5, 1.0, 2.0, 3.0, 3.5, 3.5,   # 06-11
    3.0, 3.0, 3.5, 3.5, 3.0, 3.5,   # 12-17
    4.0, 4.0, 3.5, 2.5, 1.5, 0.8,   # 18-23
]

# How many transactions per day (Gaussian around 50, min 20)
_DAILY_MEAN = 50
_DAILY_STD  = 12


def _random_hour() -> int:
    return random.choices(range(24), weights=_HOUR_WEIGHTS, k=1)[0]


def _random_datetime(d: date) -> str:
    h  = _random_hour()
    m  = random.randint(0, 59)
    s  = random.randint(0, 59)
    dt = datetime(d.year, d.month, d.day, h, m, s, tzinfo=timezone.utc)
    return dt.isoformat()


def _generate_transaction(d: date, error_rate: float = 0.10) -> dict:
    supplier     = random.choice(SUPPLIERS)
    description, category, base_price = random.choice(supplier["products"])

    # Slight price variation ±15%
    value = round(base_price * random.uniform(0.85, 1.15), 2)

    # Buyer country must differ from seller country (cross-border)
    buyer_country = random.choice(
        [c for c in COUNTRIES if c != supplier["country"]]
    )

    correct_rate = VAT_RATES[buyer_country][category]

    # Introduce error: supplier uses their own country rate instead
    if random.random() < error_rate:
        wrong_rate = VAT_RATES[supplier["country"]].get(category, correct_rate)
        vat_rate   = wrong_rate
        has_error  = int(wrong_rate != correct_rate)
    else:
        vat_rate  = correct_rate
        has_error = 0

    vat_amount = round(value * vat_rate, 2)
    tx_date    = _random_datetime(d)
    tx_id      = str(uuid.uuid4())

    row = {
        "transaction_id":   tx_id,
        "transaction_date": tx_date,
        "seller_id":        supplier["id"],
        "seller_name":      supplier["name"],
        "seller_country":   supplier["country"],
        "item_description": description,
        "item_category":    category,
        "value":            value,
        "vat_rate":         vat_rate,
        "vat_amount":       vat_amount,
        "buyer_country":    buyer_country,
        "correct_vat_rate": correct_rate,
        "has_error":        has_error,
        "xml_message":      None,       # filled below
        "created_at":       tx_date,
    }
    row["xml_message"] = transaction_to_xml(row)
    return row


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def seed_european_custom_db() -> int:
    init_european_custom_db()
    start = date(2025, 9, 1)
    end   = date(2026, 2, 28)
    rows  = []
    for d in _date_range(start, end):
        n = max(20, int(random.gauss(_DAILY_MEAN, _DAILY_STD)))
        rows.extend(_generate_transaction(d) for _ in range(n))
    # Sort by date so the DB is chronological
    rows.sort(key=lambda r: r["transaction_date"])
    bulk_insert(rows, EUROPEAN_CUSTOM_DB)
    return len(rows)


def _scenario_transactions(d: date) -> list[dict]:
    """
    Alarm scenario: TechZone GmbH (SUP001, DE) → IE
    During week 2 of March (08–14), 8 transactions per day are injected where
    the supplier fraudulently applies 0% VAT instead of Ireland's standard
    23% rate on electronics.  This drives the 7-day VAT/value ratio from ~19%
    (historical correct electronics rate) to ~0%, triggering the alarm.
    Only IE-bound transactions are flagged suspicious per SUSPICIOUS_COUNTRIES.
    """
    SCENARIO_SUPPLIER = next(s for s in SUPPLIERS if s["id"] == "SUP001")
    BUYER_COUNTRY  = "IE"
    WRONG_VAT_RATE = 0.00   # Fraudulent zero-rate (correct is 23% for electronics)
    CORRECT_RATE   = VAT_RATES[BUYER_COUNTRY]["electronics"]   # 0.23

    rows = []
    # Only pick electronics products for the scenario
    electronics_products = [(d, c, p) for d, c, p in SCENARIO_SUPPLIER["products"] if c == "electronics"]
    for _ in range(8):
        description, category, base_price = random.choice(electronics_products)
        value      = round(base_price * random.uniform(0.85, 1.15), 2)
        vat_rate   = WRONG_VAT_RATE
        vat_amount = round(value * vat_rate, 2)
        tx_date    = _random_datetime(d)
        import uuid as _uuid
        tx_id      = str(_uuid.uuid4())
        row = {
            "transaction_id":   tx_id,
            "transaction_date": tx_date,
            "seller_id":        SCENARIO_SUPPLIER["id"],
            "seller_name":      SCENARIO_SUPPLIER["name"],
            "seller_country":   SCENARIO_SUPPLIER["country"],
            "item_description": description,
            "item_category":    category,
            "value":            value,
            "vat_rate":         vat_rate,
            "vat_amount":       vat_amount,
            "buyer_country":    BUYER_COUNTRY,
            "correct_vat_rate": CORRECT_RATE,
            "has_error":        1,
            "xml_message":      None,
            "created_at":       tx_date,
            "fired":            0,
        }
        from lib.xml_generator import transaction_to_xml
        row["xml_message"] = transaction_to_xml(row)
        rows.append(row)
    return rows


def _rescale_to_sim_window(rows: list[dict]) -> None:
    """
    Linearly remap each row's `transaction_date` (and `created_at`) from the
    original generation range [first_date, last_date] into the configured
    simulation window [SIM_START_DT, SIM_END_DT] — preserving relative ordering
    and proportional spacing. Re-generates `xml_message` so the embedded
    timestamp matches the rescaled stored value.

    Mutates `rows` in place. Assumes `rows` is already sorted by
    transaction_date.
    """
    if not rows:
        return
    src_first = datetime.fromisoformat(rows[0]["transaction_date"])
    src_last  = datetime.fromisoformat(rows[-1]["transaction_date"])
    src_span_sec = max(1.0, (src_last - src_first).total_seconds())
    dst_span_sec = (SIM_END_DT - SIM_START_DT).total_seconds()

    for r in rows:
        src_dt = datetime.fromisoformat(r["transaction_date"])
        frac   = (src_dt - src_first).total_seconds() / src_span_sec
        new_dt = SIM_START_DT + timedelta(seconds=frac * dst_span_sec)
        new_iso = new_dt.isoformat()
        r["transaction_date"] = new_iso
        r["created_at"]       = new_iso
        # XML embeds the transaction_date — regenerate so it matches.
        r["xml_message"]      = transaction_to_xml(r)


def seed_simulation_db() -> int:
    init_simulation_db()
    start = date(2026, 3, 1)
    end   = date(2026, 3, 31)
    rows  = []
    # Scenario week 2 = March 8–14
    scenario_days = {date(2026, 3, d) for d in range(8, 15)}
    for d in _date_range(start, end):
        n = max(20, int(random.gauss(_DAILY_MEAN, _DAILY_STD)))
        rows.extend(_generate_transaction(d) for _ in range(n))
        if d in scenario_days:
            rows.extend(_scenario_transactions(d))
    rows.sort(key=lambda r: r["transaction_date"])
    # Compress the month-long generation range into the 15-minute sim window.
    _rescale_to_sim_window(rows)
    # Add fired=0 for simulation DB
    for r in rows:
        r["fired"] = 0
    # Use custom bulk insert for simulation DB
    import sqlite3
    from lib.config import SIMULATION_DB
    conn = sqlite3.connect(SIMULATION_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    with conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO transactions
            (transaction_id, transaction_date, seller_id, seller_name,
             seller_country, item_description, item_category,
             value, vat_rate, vat_amount, buyer_country,
             correct_vat_rate, has_error, xml_message, created_at, fired)
            VALUES
            (:transaction_id, :transaction_date, :seller_id, :seller_name,
             :seller_country, :item_description, :item_category,
             :value, :vat_rate, :vat_amount, :buyer_country,
             :correct_vat_rate, :has_error, :xml_message, :created_at, :fired)
            """,
            rows,
        )
    conn.close()
    return len(rows)
