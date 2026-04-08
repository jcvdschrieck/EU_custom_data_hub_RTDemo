"""
VAT ratio alarm checker.

Upon each transaction arrival:
  1. Compute VAT/value ratio for supplier + buyer_country over the last 7 days
     (using transactions already in the European Custom DB).
  2. Compare to the ratio over the preceding 8 weeks (days −63 → −7).
  3. If |current − historical| / historical > 25% AND no active alarm exists
     for this supplier/country pair → raise a new alarm (7-day expiry).
  4. While an alarm is active, tag every new transaction from that pair as
     suspicious. Do NOT raise a duplicate alarm.

Scenario note
─────────────
TechZone GmbH (SUP001, DE) → IE is seeded with zero-rate fraud in week 2 of March
(8–14 Mar 2026): electronics are billed at 0% instead of the correct 23%.
This drives the 7-day VAT/value ratio from ~19% to ~0%, far exceeding the 25%
deviation threshold and triggering an alarm.

Only Ireland-bound transactions are tagged as suspicious (SUSPICIOUS_COUNTRIES).
Other supplier/country pairs may also trigger the ratio alarm, but only IE
transactions are pushed to the suspicious transactions queue.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from lib.config import EUROPEAN_CUSTOM_DB

MIN_CURRENT_TX    = 3    # minimum transactions needed in the 7-day window
MIN_HISTORICAL_TX = 5    # minimum transactions needed in the 8-week baseline
DEVIATION_THRESHOLD = 0.25   # 25 %

# Only transactions destined for these countries are tagged suspicious and
# forwarded to the agent processing queue.
SUSPICIOUS_COUNTRIES: set[str] = {"IE"}


# ── Internal DB helpers (read from European Custom DB) ────────────────────────

def _conn():
    c = sqlite3.connect(EUROPEAN_CUSTOM_DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _vat_ratio(
    supplier_id: str,
    buyer_country: str,
    date_from: str,
    date_to: str,
    extra_value: float = 0.0,
    extra_vat: float = 0.0,
    extra_count: int = 0,
) -> dict | None:
    """
    Return {ratio, count} for the supplier/country window, or None if too few rows.

    extra_value / extra_vat / extra_count let the caller inject the current
    transaction's figures without requiring it to already be stored in the DB.
    This allows _alarm_worker to subscribe to 'incoming' in parallel with
    _db_store_worker rather than being chained after it.
    """
    conn = _conn()
    row = conn.execute(
        """
        SELECT COUNT(*) as n,
               SUM(vat_amount) as total_vat,
               SUM(value)      as total_value
        FROM transactions
        WHERE seller_id    = ?
          AND buyer_country = ?
          AND transaction_date >= ?
          AND transaction_date <= ?
        """,
        (supplier_id, buyer_country, date_from, date_to),
    ).fetchone()
    conn.close()
    n           = (row["n"]           or 0) + extra_count
    total_value = (row["total_value"] or 0) + extra_value
    total_vat   = (row["total_vat"]   or 0) + extra_vat
    if not n or not total_value:
        return None
    return {"ratio": total_vat / total_value, "count": n}


def _get_active_alarm(alarm_key: str, as_of: str) -> dict | None:
    """Return the active alarm for this key if one exists and has not expired."""
    conn = _conn()
    row = conn.execute(
        """
        SELECT * FROM alarms
        WHERE alarm_key = ? AND active = 1 AND expires_at > ?
        ORDER BY id DESC LIMIT 1
        """,
        (alarm_key, as_of),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _insert_alarm(alarm_key, supplier_id, supplier_name, buyer_country,
                  trigger_tx_id, raised_at, expires_at,
                  ratio_current, ratio_historical, deviation_pct) -> int:
    conn = _conn()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO alarms
            (alarm_key, supplier_id, supplier_name, buyer_country,
             trigger_tx_id, raised_at, expires_at,
             ratio_current, ratio_historical, deviation_pct, active)
            VALUES (?,?,?,?,?,?,?,?,?,?,1)
            """,
            (alarm_key, supplier_id, supplier_name, buyer_country,
             trigger_tx_id, raised_at, expires_at,
             ratio_current, ratio_historical, deviation_pct),
        )
        alarm_id = cur.lastrowid
    conn.close()
    return alarm_id


def _mark_suspicious(transaction_id: str, alarm_id: int) -> None:
    conn = _conn()
    with conn:
        conn.execute(
            "UPDATE transactions SET suspicious=1, alarm_id=? WHERE transaction_id=?",
            (alarm_id, transaction_id),
        )
    conn.close()


# ── Public entry point ────────────────────────────────────────────────────────

def check_alarm(tx: dict) -> dict | None:
    """
    Run the alarm check for a just-inserted transaction.

    Returns a result dict when the transaction is suspicious:
        {
            "suspicious":  True,
            "alarm_id":    int,          # DB id of the active alarm
            "new_alarm":   dict | None,  # populated only when a new alarm is raised
        }
    Returns None when the transaction is not suspicious.

    Call this AFTER the transaction has been written to the European Custom DB
    (the ratio queries read from the transactions table).

    NOTE: this function intentionally does NOT update the transaction's
    suspicious flag — that is the responsibility of the DB-flag subscriber
    on the "alarm_fired" broker topic.
    """
    supplier_id   = tx["seller_id"]
    supplier_name = tx["seller_name"]
    buyer_country = tx["buyer_country"]
    tx_date       = tx["transaction_date"]      # ISO string
    tx_id         = tx["transaction_id"]
    alarm_key     = f"{supplier_id}|{buyer_country}"

    # Only raise alarms for SUSPICIOUS_COUNTRIES
    if buyer_country not in SUSPICIOUS_COUNTRIES:
        return None

    # Parse simulation time
    sim_dt = datetime.fromisoformat(tx_date[:19]).replace(tzinfo=timezone.utc)

    # ── 1. Check for existing active alarm ────────────────────────────────────
    active = _get_active_alarm(alarm_key, tx_date[:19])
    if active:
        # Transaction falls under an active alarm — flag it suspicious
        # but do NOT raise a duplicate alarm record.
        return {"suspicious": True, "alarm_id": active["id"], "new_alarm": None}

    # ── 2. Compute time windows ───────────────────────────────────────────────
    w7_from  = (sim_dt - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    w7_to    = tx_date[:19]
    w8w_from = (sim_dt - timedelta(days=63)).strftime("%Y-%m-%dT%H:%M:%S")
    w8w_to   = (sim_dt - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

    # Include the current transaction in the 7-day ratio directly so the
    # alarm checker does not need the row to be committed to the DB first.
    current    = _vat_ratio(
        supplier_id, buyer_country, w7_from, w7_to,
        extra_value=tx.get("value", 0.0),
        extra_vat=tx.get("vat_amount", 0.0),
        extra_count=1,
    )
    # Historical baseline is past data only — no injection needed.
    historical = _vat_ratio(supplier_id, buyer_country, w8w_from, w8w_to)

    if not current    or current["count"]    < MIN_CURRENT_TX:
        return None
    if not historical or historical["count"] < MIN_HISTORICAL_TX:
        return None

    ratio_curr = current["ratio"]
    ratio_hist = historical["ratio"]

    if ratio_hist == 0:
        return None

    deviation = abs(ratio_curr - ratio_hist) / ratio_hist

    if deviation <= DEVIATION_THRESHOLD:
        return None

    # ── 3. Raise alarm ────────────────────────────────────────────────────────
    raised_at  = tx_date[:19]
    expires_at = (sim_dt + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")

    alarm_id = _insert_alarm(
        alarm_key=alarm_key,
        supplier_id=supplier_id,
        supplier_name=supplier_name,
        buyer_country=buyer_country,
        trigger_tx_id=tx_id,
        raised_at=raised_at,
        expires_at=expires_at,
        ratio_current=round(ratio_curr, 6),
        ratio_historical=round(ratio_hist, 6),
        deviation_pct=round(deviation * 100, 1),
    )

    new_alarm = {
        "id":               alarm_id,
        "alarm_key":        alarm_key,
        "supplier_name":    supplier_name,
        "buyer_country":    buyer_country,
        "raised_at":        raised_at,
        "expires_at":       expires_at,
        "ratio_current":    round(ratio_curr * 100, 2),
        "ratio_historical": round(ratio_hist * 100, 2),
        "deviation_pct":    round(deviation * 100, 1),
        "active":           1,
    }
    return {"suspicious": True, "alarm_id": alarm_id, "new_alarm": new_alarm}


# ── Bootstrap helper ──────────────────────────────────────────────────────────

def bootstrap_scenario_alarm() -> None:
    """
    Pre-seed the VAT ratio alarm for the TechZone GmbH (SUP001) → IE scenario
    so that flagging begins from the very first simulation transaction.

    Called at sim_start (fired_count == 0) and after sim_reset.
    Uses the actual historical ratio in the European Custom DB (Sep 2025 – Feb 2026)
    and models the fraudulent current ratio as near-zero (0% VAT applied).
    """
    SUPPLIER_ID   = "SUP001"
    SUPPLIER_NAME = "TechZone GmbH"
    BUYER_COUNTRY = "IE"
    ALARM_KEY     = f"{SUPPLIER_ID}|{BUYER_COUNTRY}"

    # Do not double-insert if already active
    if _get_active_alarm(ALARM_KEY, "2026-03-01T00:00:00"):
        return

    # 8-week historical window as the alarm_checker would compute for sim day 1
    # (63 → 7 days before 2026-03-01)
    hist_from = "2025-12-28T00:00:00"
    hist_to   = "2026-02-22T00:00:00"
    hist = _vat_ratio(SUPPLIER_ID, BUYER_COUNTRY, hist_from, hist_to)
    if not hist or hist["count"] < MIN_HISTORICAL_TX:
        return   # Historical data not seeded yet — cannot bootstrap

    ratio_hist = hist["ratio"]
    ratio_curr = 0.001   # near-zero: fraudulent 0%-VAT transactions
    deviation  = abs(ratio_curr - ratio_hist) / ratio_hist if ratio_hist else 0.0

    _insert_alarm(
        alarm_key        = ALARM_KEY,
        supplier_id      = SUPPLIER_ID,
        supplier_name    = SUPPLIER_NAME,
        buyer_country    = BUYER_COUNTRY,
        trigger_tx_id    = "bootstrap",
        raised_at        = "2026-02-28T00:00:00",
        expires_at       = "2026-04-07T00:00:00",   # covers full simulation + 7 days
        ratio_current    = round(ratio_curr, 6),
        ratio_historical = round(ratio_hist, 6),
        deviation_pct    = round(deviation * 100, 1),
    )
