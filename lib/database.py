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

_AGENT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS agent_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id    TEXT    NOT NULL,
    seller_name       TEXT    NOT NULL,
    buyer_country     TEXT    NOT NULL,
    item_description  TEXT    NOT NULL,
    item_category     TEXT    NOT NULL,
    value             REAL    NOT NULL,
    vat_rate          REAL    NOT NULL,
    correct_vat_rate  REAL    NOT NULL,
    verdict           TEXT    NOT NULL,
    reasoning         TEXT    NOT NULL,
    legislation_refs  TEXT,
    sent_to_ireland   INTEGER NOT NULL DEFAULT 0,
    processed_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_log_tx ON agent_log(transaction_id);
"""

_IRELAND_QUEUE_DDL = """
CREATE TABLE IF NOT EXISTS ireland_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id   TEXT    NOT NULL,
    seller_name      TEXT    NOT NULL,
    seller_country   TEXT    NOT NULL,
    item_description TEXT    NOT NULL,
    item_category    TEXT    NOT NULL,
    value            REAL    NOT NULL,
    vat_rate         REAL    NOT NULL,
    correct_vat_rate REAL    NOT NULL,
    vat_amount       REAL    NOT NULL,
    transaction_date TEXT    NOT NULL,
    alarm_key        TEXT    NOT NULL,
    deviation_pct    REAL,
    ratio_current    REAL,
    ratio_historical REAL,
    agent_verdict    TEXT    NOT NULL,
    agent_reasoning  TEXT    NOT NULL,
    queued_at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ireland_queue_tx ON ireland_queue(transaction_id);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _migrate_european_custom_db(conn: sqlite3.Connection) -> None:
    """Add columns / tables introduced after initial schema."""
    for col, definition in [
        ("suspicious",     "INTEGER DEFAULT 0"),
        ("alarm_id",       "INTEGER DEFAULT NULL"),
        ("suspicion_level","TEXT    DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass   # already exists
    for ddl in [_ALARM_DDL, _AGENT_LOG_DDL, _IRELAND_QUEUE_DDL]:
        for stmt in ddl.strip().split(";"):
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
            INSERT INTO transactions
            (transaction_id, transaction_date, seller_id, seller_name,
             seller_country, item_description, item_category,
             value, vat_rate, vat_amount, buyer_country,
             correct_vat_rate, has_error, xml_message, created_at)
            VALUES
            (:transaction_id, :transaction_date, :seller_id, :seller_name,
             :seller_country, :item_description, :item_category,
             :value, :vat_rate, :vat_amount, :buyer_country,
             :correct_vat_rate, :has_error, :xml_message, :created_at)
            ON CONFLICT(transaction_id) DO UPDATE SET
              transaction_date  = excluded.transaction_date,
              seller_name       = excluded.seller_name,
              item_description  = excluded.item_description,
              value             = excluded.value,
              vat_rate          = excluded.vat_rate,
              vat_amount        = excluded.vat_amount,
              correct_vat_rate  = excluded.correct_vat_rate,
              has_error         = excluded.has_error
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


def get_transaction_by_id(transaction_id: str) -> dict | None:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    row = conn.execute(
        "SELECT * FROM transactions WHERE transaction_id=? LIMIT 1",
        (transaction_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


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

def get_next_sim_transaction() -> dict | None:
    """Return the single next unfired transaction in chronological order."""
    conn = _connect(SIMULATION_DB)
    row = conn.execute(
        "SELECT * FROM transactions WHERE fired=0 ORDER BY transaction_date LIMIT 1"
    ).fetchone()
    conn.close()
    return dict(row) if row else None


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
    """
    Prepare the European Custom DB for a fresh simulation run:
      - Remove simulation-period transactions (≥ 2026-03-01) so the pipeline
        can re-insert them with updated risk scores.
      - Clear alarms, agent log and ireland queue.
      - Reset suspicious flags on the retained historical records.
    Historical rows (Sep 2025 – Feb 2026) are kept intact as baseline context.
    """
    from lib.config import SIM_START_STR
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute("DELETE FROM transactions WHERE transaction_date >= ?", (SIM_START_STR,))
        conn.execute("DELETE FROM alarms")
        conn.execute("DELETE FROM agent_log")
        conn.execute("DELETE FROM ireland_queue")
        conn.execute(
            "UPDATE transactions SET suspicious=0, alarm_id=NULL, suspicion_level=NULL"
        )
    conn.close()


def historical_transaction_count() -> int:
    """Number of pre-simulation transactions in the European Custom DB."""
    from lib.config import SIM_START_STR
    conn = _connect(EUROPEAN_CUSTOM_DB)
    n = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE transaction_date < ?", (SIM_START_STR,)
    ).fetchone()[0]
    conn.close()
    return n


# ── Agent log ─────────────────────────────────────────────────────────────────

def insert_agent_log(entry: dict) -> None:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_log
            (transaction_id, seller_name, buyer_country, item_description,
             item_category, value, vat_rate, correct_vat_rate,
             verdict, reasoning, legislation_refs, sent_to_ireland, processed_at)
            VALUES
            (:transaction_id, :seller_name, :buyer_country, :item_description,
             :item_category, :value, :vat_rate, :correct_vat_rate,
             :verdict, :reasoning, :legislation_refs, :sent_to_ireland, :processed_at)
            """,
            entry,
        )
    conn.close()


def get_agent_log(limit: int = 100) -> list[dict]:
    import json as _json
    conn = _connect(EUROPEAN_CUSTOM_DB)
    rows = conn.execute(
        "SELECT * FROM agent_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["legislation_refs"] = _json.loads(d["legislation_refs"]) if d.get("legislation_refs") else []
        except Exception:
            d["legislation_refs"] = []
        result.append(d)
    return result


def get_agent_log_by_tx(transaction_id: str) -> dict | None:
    import json as _json
    conn = _connect(EUROPEAN_CUSTOM_DB)
    row = conn.execute(
        "SELECT * FROM agent_log WHERE transaction_id=? ORDER BY id DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["legislation_refs"] = _json.loads(d["legislation_refs"]) if d.get("legislation_refs") else []
    except Exception:
        d["legislation_refs"] = []
    return d


def flag_transaction_suspicious(
    transaction_id: str,
    alarm_id: int | None,
    risk_score: str = "amber",
) -> None:
    """
    DB-subscriber action triggered by the Release_Event_Broker.
    Updates the stored transaction record using its identifier — sets
    suspicious=1, links the alarm (if any), and stores the computed
    risk_score ('amber' or 'red') as suspicion_level.
    """
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            "UPDATE transactions "
            "SET suspicious=1, alarm_id=?, suspicion_level=? "
            "WHERE transaction_id=?",
            (alarm_id, risk_score, transaction_id),
        )
    conn.close()


def update_suspicion_level(transaction_id: str, level: str) -> None:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            "UPDATE transactions SET suspicion_level=? WHERE transaction_id=?",
            (level, transaction_id),
        )
    conn.close()


def clear_suspicious_flag(transaction_id: str) -> None:
    """Remove suspicious flag when agent clears the transaction."""
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            "UPDATE transactions SET suspicious=0, alarm_id=NULL, suspicion_level=NULL "
            "WHERE transaction_id=?",
            (transaction_id,),
        )
    conn.close()


# ── Ireland queue ─────────────────────────────────────────────────────────────

def insert_ireland_queue(entry: dict) -> None:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO ireland_queue
            (transaction_id, seller_name, seller_country, item_description,
             item_category, value, vat_rate, correct_vat_rate, vat_amount,
             transaction_date, alarm_key, deviation_pct, ratio_current,
             ratio_historical, agent_verdict, agent_reasoning, queued_at)
            VALUES
            (:transaction_id, :seller_name, :seller_country, :item_description,
             :item_category, :value, :vat_rate, :correct_vat_rate, :vat_amount,
             :transaction_date, :alarm_key, :deviation_pct, :ratio_current,
             :ratio_historical, :agent_verdict, :agent_reasoning, :queued_at)
            """,
            entry,
        )
    conn.close()


def get_ireland_queue(limit: int = 100) -> list[dict]:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    rows = conn.execute(
        "SELECT * FROM ireland_queue ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_ireland_case(transaction_id: str) -> dict | None:
    """Return ireland_queue entry merged with agent_log detail (legislation refs)."""
    import json as _json
    conn = _connect(EUROPEAN_CUSTOM_DB)
    iq = conn.execute(
        "SELECT * FROM ireland_queue WHERE transaction_id=? LIMIT 1",
        (transaction_id,),
    ).fetchone()
    al = conn.execute(
        "SELECT * FROM agent_log WHERE transaction_id=? ORDER BY id DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    conn.close()
    if not iq:
        return None
    result = dict(iq)
    if al:
        try:
            result["legislation_refs"] = _json.loads(al["legislation_refs"]) if al["legislation_refs"] else []
        except Exception:
            result["legislation_refs"] = []
        result["agent_reasoning_full"] = al["reasoning"]
    else:
        result["legislation_refs"] = []
    return result
