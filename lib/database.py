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
    created_at       TEXT    NOT NULL,
    -- Producer (non-EU manufacturer) sourced by the seller/reseller.
    -- Populated by the seeder for new rows. May be NULL on rows from
    -- older DBs created before the two-tier party model was introduced.
    producer_id      TEXT,
    producer_name    TEXT,
    producer_country TEXT,
    producer_city    TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_date     ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_tx_seller   ON transactions(seller_name);
CREATE INDEX IF NOT EXISTS idx_tx_buyer    ON transactions(buyer_country);
CREATE INDEX IF NOT EXISTS idx_tx_producer ON transactions(producer_country);
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


# ── Data hub schema (3 dark-purple tables from the data model diagram) ───────
#
# These three tables form the new normalised data hub. They live alongside the
# legacy `transactions` table (which the alarm checker still reads for the
# 7-day VAT-ratio baseline) and are populated by the _data_hub_writer polling
# worker on a 30-s tick. PK / FK is sales_order_line_item_SKU = the per-line
# unique identifier f"{so_id}-{n:03d}".

_SO_LI_DDL = """
CREATE TABLE IF NOT EXISTS sales_order_line_item (
    sales_order_line_item_SKU TEXT PRIMARY KEY,
    so_id                     TEXT NOT NULL,
    line_item_name            TEXT NOT NULL,
    line_item_SKU             TEXT NOT NULL,
    line_item_description     TEXT,
    line_item_price           REAL,
    product_category          TEXT,
    deemed_importer_id        TEXT,
    deemed_importer_name      TEXT,
    deemed_importer_country   TEXT,
    seller_id                 TEXT,
    seller_name               TEXT,
    seller_city               TEXT,
    origin_country            TEXT,
    destination_country       TEXT,
    dest_country_region       TEXT,
    VAT_pct                   REAL,
    VAT_paid                  REAL,
    date                      TEXT
);
CREATE INDEX IF NOT EXISTS idx_so_li_so_id     ON sales_order_line_item(so_id);
CREATE INDEX IF NOT EXISTS idx_so_li_date      ON sales_order_line_item(date);
CREATE INDEX IF NOT EXISTS idx_so_li_region    ON sales_order_line_item(dest_country_region);
CREATE INDEX IF NOT EXISTS idx_so_li_importer  ON sales_order_line_item(deemed_importer_id);
"""

_LI_RISK_DDL = """
CREATE TABLE IF NOT EXISTS line_item_risk (
    sales_order_line_item_SKU TEXT PRIMARY KEY,
    risk_score_numeric        INTEGER,
    risk_level                TEXT,
    risk_description          TEXT,
    suggested_risk_action     TEXT,
    FOREIGN KEY (sales_order_line_item_SKU)
        REFERENCES sales_order_line_item(sales_order_line_item_SKU)
);
CREATE INDEX IF NOT EXISTS idx_li_risk_level ON line_item_risk(risk_level);
"""

_LI_AI_DDL = """
CREATE TABLE IF NOT EXISTS line_item_ai_analysis (
    sales_order_line_item_SKU TEXT PRIMARY KEY,
    analysis_outcome          TEXT,
    analysis_description      TEXT,
    confidence_score          REAL,
    source                    TEXT,
    correct_product_category  TEXT,
    correct_vat_pct           REAL,
    correct_vat_value         REAL,
    vat_exposure              REAL,
    FOREIGN KEY (sales_order_line_item_SKU)
        REFERENCES sales_order_line_item(sales_order_line_item_SKU)
);
CREATE INDEX IF NOT EXISTS idx_li_ai_outcome ON line_item_ai_analysis(analysis_outcome);
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
        ("suspicious",       "INTEGER DEFAULT 0"),
        ("alarm_id",         "INTEGER DEFAULT NULL"),
        ("suspicion_level",  "TEXT    DEFAULT NULL"),
        # Two-tier party model — non-EU producer (the line item Seller).
        ("producer_id",      "TEXT    DEFAULT NULL"),
        ("producer_name",    "TEXT    DEFAULT NULL"),
        ("producer_country", "TEXT    DEFAULT NULL"),
        ("producer_city",    "TEXT    DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {definition}")
        except sqlite3.OperationalError:
            pass   # already exists
    for ddl in [
        _ALARM_DDL, _AGENT_LOG_DDL, _IRELAND_QUEUE_DDL,
        _SO_LI_DDL, _LI_RISK_DDL, _LI_AI_DDL,
    ]:
        for stmt in ddl.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)


def _migrate_simulation_db(conn: sqlite3.Connection) -> None:
    """Add producer columns to existing simulation.db files (the production
    table column list lives in _TX_DDL but older DB files predate it)."""
    for col in ("producer_id", "producer_name", "producer_country", "producer_city"):
        try:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} TEXT DEFAULT NULL")
        except sqlite3.OperationalError:
            pass   # already exists


def init_european_custom_db() -> None:
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        # Run the CREATE TABLE first (without indexes that reference
        # columns added by migration). Then migrate to add any missing
        # columns. Finally create the indexes.
        for stmt in _TX_DDL.strip().split(";"):
            s = stmt.strip()
            if not s:
                continue
            # Skip CREATE INDEX statements on first pass — columns
            # they reference may not exist yet on older DBs.
            if s.upper().startswith("CREATE INDEX"):
                continue
            try:
                conn.execute(s)
            except sqlite3.OperationalError:
                pass  # table already exists
        # Add any missing columns (producer_*, suspicious, etc.)
        _migrate_european_custom_db(conn)
        # Now create indexes — all columns are guaranteed to exist.
        for stmt in _TX_DDL.strip().split(";"):
            s = stmt.strip()
            if s and s.upper().startswith("CREATE INDEX"):
                try:
                    conn.execute(s)
                except sqlite3.OperationalError:
                    pass  # index already exists
    conn.close()
    # Backfill the new data hub table from the legacy transactions table.
    # Idempotent (uses INSERT OR REPLACE keyed on the synthetic SKU), so it's
    # safe to call on every startup. Skip if the legacy table is empty or the
    # backfill is already complete.
    try:
        conn = _connect(EUROPEAN_CUSTOM_DB)
        legacy_n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        new_n    = conn.execute("SELECT COUNT(*) FROM sales_order_line_item").fetchone()[0]
        conn.close()
        if legacy_n > 0 and new_n < legacy_n:
            n = backfill_sales_order_line_item_from_transactions()
            print(f"[data_hub] backfilled {n} rows into sales_order_line_item "
                  f"({legacy_n} legacy rows, {new_n} already present)")
    except Exception as exc:
        print(f"[data_hub] backfill skipped: {exc}")


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
        # Producer columns may be missing on old simulation.db files.
        _migrate_simulation_db(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fired "
            "ON transactions(fired, transaction_date)"
        )
    conn.close()


# ── European Custom DB write ───────────────────────────────────────────────────

def insert_transaction(row: dict) -> None:
    # Ensure the producer keys exist (older message paths may not set them).
    row.setdefault("producer_id", None)
    row.setdefault("producer_name", None)
    row.setdefault("producer_country", None)
    row.setdefault("producer_city", None)
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            """
            INSERT INTO transactions
            (transaction_id, transaction_date, seller_id, seller_name,
             seller_country, item_description, item_category,
             value, vat_rate, vat_amount, buyer_country,
             correct_vat_rate, has_error, xml_message, created_at,
             producer_id, producer_name, producer_country, producer_city)
            VALUES
            (:transaction_id, :transaction_date, :seller_id, :seller_name,
             :seller_country, :item_description, :item_category,
             :value, :vat_rate, :vat_amount, :buyer_country,
             :correct_vat_rate, :has_error, :xml_message, :created_at,
             :producer_id, :producer_name, :producer_country, :producer_city)
            ON CONFLICT(transaction_id) DO UPDATE SET
              transaction_date  = excluded.transaction_date,
              seller_name       = excluded.seller_name,
              item_description  = excluded.item_description,
              value             = excluded.value,
              vat_rate          = excluded.vat_rate,
              vat_amount        = excluded.vat_amount,
              correct_vat_rate  = excluded.correct_vat_rate,
              has_error         = excluded.has_error,
              producer_id       = excluded.producer_id,
              producer_name     = excluded.producer_name,
              producer_country  = excluded.producer_country,
              producer_city     = excluded.producer_city
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
             correct_vat_rate, has_error, xml_message, created_at,
             producer_id, producer_name, producer_country, producer_city)
            VALUES
            (:transaction_id, :transaction_date, :seller_id, :seller_name,
             :seller_country, :item_description, :item_category,
             :value, :vat_rate, :vat_amount, :buyer_country,
             :correct_vat_rate, :has_error, :xml_message, :created_at,
             :producer_id, :producer_name, :producer_country, :producer_city)
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


# ── Data hub upserts (3 dark-purple tables) ──────────────────────────────────

def upsert_sales_order_line_item(row: dict) -> None:
    """
    Insert-or-replace a row in sales_order_line_item.

    Idempotent — re-receiving the same line is a no-op (the keys never change
    because they're derived deterministically from so_id + line_number).
    """
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            """
            INSERT INTO sales_order_line_item
            (sales_order_line_item_SKU, so_id, line_item_name, line_item_SKU,
             line_item_description, line_item_price, product_category,
             deemed_importer_id, deemed_importer_name, deemed_importer_country,
             seller_id, seller_name, seller_city, origin_country,
             destination_country, dest_country_region,
             VAT_pct, VAT_paid, date)
            VALUES
            (:sales_order_line_item_SKU, :so_id, :line_item_name, :line_item_SKU,
             :line_item_description, :line_item_price, :product_category,
             :deemed_importer_id, :deemed_importer_name, :deemed_importer_country,
             :seller_id, :seller_name, :seller_city, :origin_country,
             :destination_country, :dest_country_region,
             :VAT_pct, :VAT_paid, :date)
            ON CONFLICT(sales_order_line_item_SKU) DO UPDATE SET
              line_item_description   = excluded.line_item_description,
              line_item_price         = excluded.line_item_price,
              product_category        = excluded.product_category,
              deemed_importer_id      = excluded.deemed_importer_id,
              deemed_importer_name    = excluded.deemed_importer_name,
              deemed_importer_country = excluded.deemed_importer_country,
              seller_id               = excluded.seller_id,
              seller_name             = excluded.seller_name,
              seller_city             = excluded.seller_city,
              origin_country          = excluded.origin_country,
              destination_country     = excluded.destination_country,
              dest_country_region     = excluded.dest_country_region,
              VAT_pct                 = excluded.VAT_pct,
              VAT_paid                = excluded.VAT_paid,
              date                    = excluded.date
            """,
            row,
        )
    conn.close()


def bulk_upsert_sales_order_line_item(rows: list[dict]) -> int:
    """Bulk variant for the historical backfill — single transaction."""
    if not rows:
        return 0
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO sales_order_line_item
            (sales_order_line_item_SKU, so_id, line_item_name, line_item_SKU,
             line_item_description, line_item_price, product_category,
             deemed_importer_id, deemed_importer_name, deemed_importer_country,
             seller_id, seller_name, seller_city, origin_country,
             destination_country, dest_country_region,
             VAT_pct, VAT_paid, date)
            VALUES
            (:sales_order_line_item_SKU, :so_id, :line_item_name, :line_item_SKU,
             :line_item_description, :line_item_price, :product_category,
             :deemed_importer_id, :deemed_importer_name, :deemed_importer_country,
             :seller_id, :seller_name, :seller_city, :origin_country,
             :destination_country, :dest_country_region,
             :VAT_pct, :VAT_paid, :date)
            """,
            rows,
        )
    conn.close()
    return len(rows)


def upsert_line_item_risk(row: dict) -> None:
    """Insert-or-replace a row in line_item_risk."""
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            """
            INSERT INTO line_item_risk
            (sales_order_line_item_SKU, risk_score_numeric, risk_level,
             risk_description, suggested_risk_action)
            VALUES
            (:sales_order_line_item_SKU, :risk_score_numeric, :risk_level,
             :risk_description, :suggested_risk_action)
            ON CONFLICT(sales_order_line_item_SKU) DO UPDATE SET
              risk_score_numeric    = excluded.risk_score_numeric,
              risk_level            = excluded.risk_level,
              risk_description      = excluded.risk_description,
              suggested_risk_action = excluded.suggested_risk_action
            """,
            row,
        )
    conn.close()


def upsert_line_item_ai_analysis(row: dict) -> None:
    """Insert-or-replace a row in line_item_ai_analysis."""
    conn = _connect(EUROPEAN_CUSTOM_DB)
    with conn:
        conn.execute(
            """
            INSERT INTO line_item_ai_analysis
            (sales_order_line_item_SKU, analysis_outcome, analysis_description,
             confidence_score, source, correct_product_category,
             correct_vat_pct, correct_vat_value, vat_exposure)
            VALUES
            (:sales_order_line_item_SKU, :analysis_outcome, :analysis_description,
             :confidence_score, :source, :correct_product_category,
             :correct_vat_pct, :correct_vat_value, :vat_exposure)
            ON CONFLICT(sales_order_line_item_SKU) DO UPDATE SET
              analysis_outcome         = excluded.analysis_outcome,
              analysis_description     = excluded.analysis_description,
              confidence_score         = excluded.confidence_score,
              source                   = excluded.source,
              correct_product_category = excluded.correct_product_category,
              correct_vat_pct          = excluded.correct_vat_pct,
              correct_vat_value        = excluded.correct_vat_value,
              vat_exposure             = excluded.vat_exposure
            """,
            row,
        )
    conn.close()


# ── Historical backfill ──────────────────────────────────────────────────────

def backfill_sales_order_line_item_from_transactions() -> int:
    """
    One-shot migration: read every row in the legacy `transactions` table and
    insert it into `sales_order_line_item` as a single synthetic line item
    (line_number = 1, suffix `-001`). No risk / AI rows are created — those
    only exist for transactions that pass through the live pipeline.

    Idempotent: re-running is a no-op because the SKU is deterministic and we
    use INSERT OR REPLACE.

    Returns the number of rows backfilled.
    """
    from lib.regions import country_region

    conn = _connect(EUROPEAN_CUSTOM_DB)
    rows = conn.execute(
        "SELECT transaction_id, transaction_date, "
        "       seller_id, seller_name, seller_country, "
        "       producer_id, producer_name, producer_country, producer_city, "
        "       item_description, item_category, "
        "       value, vat_rate, vat_amount, buyer_country "
        "FROM transactions"
    ).fetchall()
    conn.close()

    payload: list[dict] = []
    for r in rows:
        so_id = r["transaction_id"]
        sku   = f"{so_id}-001"
        # Two-tier party model: producer = line-item Seller (non-EU origin),
        # seller_* on the legacy row = DeemedImporter (EU reseller).
        # Producer fields may be NULL for rows that predate the two-tier
        # migration — render those as empty strings to keep the column
        # populated rather than NULL.
        payload.append({
            "sales_order_line_item_SKU": sku,
            "so_id":                     so_id,
            "line_item_name":            sku,
            "line_item_SKU":             sku,
            "line_item_description":     r["item_description"],
            "line_item_price":           r["value"],
            "product_category":          r["item_category"],
            "deemed_importer_id":        r["seller_id"],
            "deemed_importer_name":      r["seller_name"],
            "deemed_importer_country":   r["seller_country"],
            "seller_id":                 r["producer_id"]      or None,
            "seller_name":               r["producer_name"]    or None,
            "seller_city":               r["producer_city"]    or None,
            "origin_country":            r["producer_country"] or None,
            "destination_country":       r["buyer_country"],
            "dest_country_region":       country_region(r["buyer_country"]),
            "VAT_pct":                   r["vat_rate"],
            "VAT_paid":                  r["vat_amount"],
            "date":                      r["transaction_date"],
        })

    return bulk_upsert_sales_order_line_item(payload)
