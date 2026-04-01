"""
SQLite operations for the European Custom Database and the simulation DB.

Schema is shared; the simulation DB adds a `fired` column to track
which March-2026 transactions have been replayed.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from lib.config import EUROPEAN_CUSTOM_DB, SIMULATION_DB

# ── Schema ────────────────────────────────────────────────────────────────────

_TX_DDL = """
CREATE TABLE IF NOT EXISTS transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id   TEXT    UNIQUE NOT NULL,
    transaction_date TEXT    NOT NULL,
    seller_id        TEXT    NOT NULL,
    seller_name      TEXT    NOT NULL,
    seller_country   TEXT    NOT NULL,
    item_description TEXT    NOT NULL,
    item_category    TEXT    NOT NULL,
    value            REAL    NOT NULL,
    vat_rate         REAL    NOT NULL,
    vat_amount       REAL    NOT NULL,
    buyer_country    TEXT    NOT NULL,
    correct_vat_rate REAL    NOT NULL,
    has_error        INTEGER NOT NULL DEFAULT 0,
    xml_message      TEXT,
    created_at       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_date    ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_tx_seller  ON transactions(seller_name);
CREATE INDEX IF NOT EXISTS idx_tx_buyer   ON transactions(buyer_country);
"""

_SIM_DDL = _TX_DDL + """
ALTER TABLE transactions ADD COLUMN fired INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_fired ON transactions(fired, transaction_date);
"""

_ALARM_DDL = """
CREATE TABLE IF NOT EXISTS alarms (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    alarm_key        TEXT    NOT NULL,
    supplier_id      TEXT    NOT NULL,
    supplier_name    TEXT    NOT NULL,
    buyer_country    TEXT    NOT NULL,
    trigger_tx_id    TEXT    NOT NULL,
    raised_at        TEXT    NOT NULL,
    expires_at       TEXT    NOT NULL,
    ratio_current    REAL    NOT NULL,
    ratio_historical REAL    NOT NULL,
    deviation_pct    REAL    NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_alarm_key     ON alarms(alarm_key, active);
CREATE INDEX IF NOT EXISTS idx_alarm_expires ON alarms(expires_at);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _migrate_european_custom_db(conn: sqlite3.Connection) -> None:
    """Add columns / tables introduced after initial schema."""
    for col, default in [("suspicious", "0"), ("alarm_id", "NULL")]:
        try:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} INTEGER DEFAULT {default}")
        except sqlite3.OperationalError:
            pass   # already exists
    for stmt in _ALARM_DDL.strip().split(";"):
        s = stmt.strip()
        if s:
            conn.execute(s)


def init_european_custom_db() -> None:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        for stmt in _TX_DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        _migrate_european_custom_db(conn)
    conn.close()


def init_simulation_db() -> None:
    conn = _connect(SIMULATION_DB)
    with conn:
        # Base table
        for stmt in _TX_DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        # fired column (ignore error if already exists)
        try:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN fired INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fired "
            "ON transactions(fired, transaction_date)"
        )
    conn.close()


# ── European Custom DB write ───────────────────────────────────────────────────

def insert_transaction(row: dict) -> None:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO transactions
            (transaction_id, transaction_date, seller_id, seller_name,
             seller_country, item_description, item_category,
             value, vat_rate, vat_amount, buyer_country,
             correct_vat_rate, has_error, xml_message, created_at)
            VALUES
            (:transaction_id, :transaction_date, :seller_id, :seller_name,
             :seller_country, :item_description, :item_category,
             :value, :vat_rate, :vat_amount, :buyer_country,
             :correct_vat_rate, :has_error, :xml_message, :created_at)
            """,
            row,
        )
    conn.close()


def bulk_insert(rows: list[dict], path: Path = EUROPEAN_CUSTOM_DB) -> None:
    conn = _connect(path)
    with conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO transactions
            (transaction_id, transaction_date, seller_id, seller_name,
             seller_country, item_description, item_category,
             value, vat_rate, vat_amount, buyer_country,
             correct_vat_rate, has_error, xml_message, created_at)
            VALUES
            (:transaction_id, :transaction_date, :seller_id, :seller_name,
             :seller_country, :item_description, :item_category,
             :value, :vat_rate, :vat_amount, :buyer_country,
             :correct_vat_rate, :has_error, :xml_message, :created_at)
            """,
            rows,
        )
    conn.close()


# ── European Custom DB read ────────────────────────────────────────────────────

def get_latest_transactions(limit: int = 30) -> list[dict]:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY transaction_date DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_transaction_count() -> int:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
    return n


def query_transactions(
    *,
    seller_name: str | None = None,
    buyer_country: str | None = None,
    seller_country: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    clauses, params = [], []
    if seller_name:
        clauses.append("seller_name = ?")
        params.append(seller_name)
    if buyer_country:
        clauses.append("buyer_country = ?")
        params.append(buyer_country)
    if seller_country:
        clauses.append("seller_country = ?")
        params.append(seller_country)
    if date_from:
        clauses.append("transaction_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("transaction_date <= ?")
        params.append(date_to + "T23:59:59")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM transactions {where} ORDER BY transaction_date DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    conn = _connect(EUROPEAN_CUSTOM_DB)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_vat_metrics(
    *,
    seller_name: str | None = None,
    buyer_country: str | None = None,
    seller_country: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Aggregate VAT metrics with optional filters."""
    clauses, params = [], []
    if seller_name:
        clauses.append("seller_name = ?")
        params.append(seller_name)
    if buyer_country:
        clauses.append("buyer_country = ?")
        params.append(buyer_country)
    if seller_country:
        clauses.append("seller_country = ?")
        params.append(seller_country)
    if date_from:
        clauses.append("transaction_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("transaction_date <= ?")
        params.append(date_to + "T23:59:59")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = _connect(EUROPEAN_CUSTOM_DB)

    totals = conn.execute(
        f"SELECT COUNT(*) as n, SUM(value) as total_value, "
        f"SUM(vat_amount) as total_vat, SUM(has_error) as errors "
        f"FROM transactions {where}",
        params,
    ).fetchone()

    by_buyer = conn.execute(
        f"SELECT buyer_country, COUNT(*) as n, SUM(vat_amount) as vat "
        f"FROM transactions {where} GROUP BY buyer_country ORDER BY vat DESC",
        params,
    ).fetchall()

    by_seller = conn.execute(
        f"SELECT seller_name, COUNT(*) as n, SUM(vat_amount) as vat "
        f"FROM transactions {where} GROUP BY seller_name ORDER BY vat DESC",
        params,
    ).fetchall()

    by_category = conn.execute(
        f"SELECT item_category, COUNT(*) as n, SUM(vat_amount) as vat "
        f"FROM transactions {where} GROUP BY item_category ORDER BY vat DESC",
        params,
    ).fetchall()

    # Daily VAT over time
    daily = conn.execute(
        f"SELECT SUBSTR(transaction_date,1,10) as day, SUM(vat_amount) as vat "
        f"FROM transactions {where} GROUP BY day ORDER BY day",
        params,
    ).fetchall()

    conn.close()
    return {
        "total_transactions": totals["n"] or 0,
        "total_value": round(totals["total_value"] or 0, 2),
        "total_vat": round(totals["total_vat"] or 0, 2),
        "error_count": totals["errors"] or 0,
        "by_buyer_country": [dict(r) for r in by_buyer],
        "by_seller": [dict(r) for r in by_seller],
        "by_category": [dict(r) for r in by_category],
        "daily_vat": [dict(r) for r in daily],
    }


# ── Simulation DB ─────────────────────────────────────────────────────────────

def get_pending_sim_transactions(up_to_date: str, batch: int = 100) -> list[dict]:
    """Return unfired simulation transactions whose date <= up_to_date."""
    conn = _connect(SIMULATION_DB)
    rows = conn.execute(
        "SELECT * FROM transactions WHERE fired=0 AND transaction_date <= ? "
        "ORDER BY transaction_date LIMIT ?",
        (up_to_date, batch),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_fired(transaction_ids: list[str]) -> None:
    conn = _connect(SIMULATION_DB)
    with conn:
        conn.executemany(
            "UPDATE transactions SET fired=1 WHERE transaction_id=?",
            [(tid,) for tid in transaction_ids],
        )
    conn.close()


def reset_simulation_db() -> None:
    conn = _connect(SIMULATION_DB)
    with conn:
        conn.execute("UPDATE transactions SET fired=0")
    conn.close()


def get_sim_counts() -> dict[str, int]:
    conn = _connect(SIMULATION_DB)
    total = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    fired = conn.execute("SELECT COUNT(*) FROM transactions WHERE fired=1").fetchone()[0]
    conn.close()
    return {"total": total, "fired": fired, "remaining": total - fired}


# ── Alarm queries (European Custom DB) ───────────────────────────────────────

def get_alarms(active_only: bool = False, limit: int = 50) -> list[dict]:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    where = "WHERE active=1" if active_only else ""
    rows = conn.execute(
        f"SELECT * FROM alarms {where} ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def expire_old_alarms(as_of: str) -> None:
    """Deactivate alarms whose expiry has passed."""
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            "UPDATE alarms SET active=0 WHERE active=1 AND expires_at <= ?",
            (as_of,),
        )
    conn.close()


def get_suspicious_transactions(limit: int = 50) -> list[dict]:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    rows = conn.execute(
        """
        SELECT t.*, a.deviation_pct, a.ratio_current, a.ratio_historical,
               a.raised_at as alarm_raised_at, a.expires_at as alarm_expires_at
        FROM transactions t
        JOIN alarms a ON t.alarm_id = a.id
        WHERE t.suspicious = 1
        ORDER BY t.transaction_date DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reset_alarms() -> None:
    """Clear all alarms and suspicious flags (called on simulation reset)."""
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute("DELETE FROM alarms")
        conn.execute("UPDATE transactions SET suspicious=0, alarm_id=NULL")
    conn.close()
