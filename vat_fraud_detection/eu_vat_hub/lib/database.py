"""SQLite backend for the EU VAT Hub.

Schema
------
invoices   — raw invoice data submitted by member states; NO risk scoring.
             Risk assessment is the responsibility of each country's own system.
line_items — one row per line item; stores factual VAT application data only.
api_log    — one row per inbound API request (written by logging middleware).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent.parent / "data" / "eu_vat.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id          TEXT PRIMARY KEY,
    invoice_number      TEXT NOT NULL,
    invoice_date        TEXT NOT NULL,

    supplier_name       TEXT NOT NULL,
    supplier_vat        TEXT,
    supplier_country    TEXT NOT NULL,

    customer_name       TEXT NOT NULL,
    customer_vat        TEXT,
    customer_country    TEXT NOT NULL,

    net_amount          REAL NOT NULL DEFAULT 0,
    vat_amount          REAL NOT NULL DEFAULT 0,
    gross_amount        REAL NOT NULL DEFAULT 0,
    currency            TEXT NOT NULL DEFAULT 'EUR',

    transaction_type    TEXT NOT NULL DEFAULT 'B2B',
    transaction_scope   TEXT NOT NULL DEFAULT 'domestic',
    vat_treatment       TEXT NOT NULL DEFAULT 'standard',
    vat_rate_applied    REAL NOT NULL DEFAULT 0,

    reporting_country   TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS line_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id       TEXT NOT NULL REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    description      TEXT NOT NULL DEFAULT '',
    product_category TEXT NOT NULL DEFAULT '',
    quantity         REAL NOT NULL DEFAULT 1,
    unit_price       REAL NOT NULL DEFAULT 0,
    vat_rate_applied REAL NOT NULL DEFAULT 0,
    net_amount       REAL NOT NULL DEFAULT 0,
    vat_amount       REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS api_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,
    method           TEXT NOT NULL,
    endpoint         TEXT NOT NULL,
    client_country   TEXT,
    status_code      INTEGER NOT NULL,
    response_time_ms REAL NOT NULL,
    records_returned INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_inv_date             ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_inv_sup_country      ON invoices(supplier_country);
CREATE INDEX IF NOT EXISTS idx_inv_cust_country     ON invoices(customer_country);
CREATE INDEX IF NOT EXISTS idx_inv_rep_country      ON invoices(reporting_country);
CREATE INDEX IF NOT EXISTS idx_inv_tx_type          ON invoices(transaction_type);
CREATE INDEX IF NOT EXISTS idx_inv_tx_scope         ON invoices(transaction_scope);
CREATE INDEX IF NOT EXISTS idx_inv_vat_treatment    ON invoices(vat_treatment);
CREATE INDEX IF NOT EXISTS idx_li_invoice           ON line_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_li_description       ON line_items(description);
CREATE INDEX IF NOT EXISTS idx_log_timestamp        ON api_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_log_client_country   ON api_log(client_country);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        for stmt in _SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)


def total_count() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]


def upsert_invoice(
    *,
    invoice_id: str,
    invoice_number: str,
    invoice_date: str,
    supplier_name: str,
    supplier_vat: str,
    supplier_country: str,
    customer_name: str,
    customer_vat: str,
    customer_country: str,
    net_amount: float,
    vat_amount: float,
    gross_amount: float,
    currency: str,
    transaction_type: str,
    transaction_scope: str,
    vat_treatment: str,
    vat_rate_applied: float,
    reporting_country: str,
    created_at: str,
    line_items: list[dict],
) -> None:
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO invoices VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                invoice_id, invoice_number, invoice_date,
                supplier_name, supplier_vat, supplier_country,
                customer_name, customer_vat, customer_country,
                net_amount, vat_amount, gross_amount, currency,
                transaction_type, transaction_scope, vat_treatment, vat_rate_applied,
                reporting_country, created_at,
            ),
        )
        c.execute("DELETE FROM line_items WHERE invoice_id = ?", (invoice_id,))
        c.executemany(
            "INSERT INTO line_items "
            "(invoice_id, description, product_category, quantity, unit_price, "
            "vat_rate_applied, net_amount, vat_amount) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    invoice_id,
                    li.get("description", ""),
                    li.get("product_category", ""),
                    li.get("quantity", 1),
                    li.get("unit_price", 0.0),
                    li.get("vat_rate_applied", 0.0),
                    li.get("net_amount", 0.0),
                    li.get("vat_amount", 0.0),
                )
                for li in line_items
            ],
        )


def write_api_log(
    *,
    timestamp: str,
    method: str,
    endpoint: str,
    client_country: str | None,
    status_code: int,
    response_time_ms: float,
    records_returned: int,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO api_log (timestamp, method, endpoint, client_country, "
            "status_code, response_time_ms, records_returned) VALUES (?,?,?,?,?,?,?)",
            (timestamp, method, endpoint, client_country,
             status_code, response_time_ms, records_returned),
        )


# ── query helpers ─────────────────────────────────────────────────────────────

def query_invoices(
    *,
    country: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    transaction_type: str | None = None,
    transaction_scope: str | None = None,
    vat_treatment: str | None = None,
    description: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[sqlite3.Row]:
    conditions, params = _build_where(
        country=country, date_from=date_from, date_to=date_to,
        transaction_type=transaction_type, transaction_scope=transaction_scope,
        vat_treatment=vat_treatment, description=description,
    )
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _conn() as c:
        return c.execute(
            f"SELECT * FROM invoices {where} "
            f"ORDER BY invoice_date DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()


def count_invoices(**kwargs) -> int:
    conditions, params = _build_where(**kwargs)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM invoices {where}", params).fetchone()[0]


def get_invoice(invoice_id: str) -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()


def get_line_items(invoice_id: str) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM line_items WHERE invoice_id = ?", (invoice_id,)
        ).fetchall()


def get_countries() -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT supplier_country FROM invoices ORDER BY supplier_country"
        ).fetchall()
    return [r[0] for r in rows]


def get_suppliers(country: str | None = None) -> list[str]:
    with _conn() as c:
        if country:
            rows = c.execute(
                "SELECT DISTINCT supplier_name FROM invoices "
                "WHERE supplier_country = ? ORDER BY supplier_name", (country,)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT DISTINCT supplier_name FROM invoices ORDER BY supplier_name"
            ).fetchall()
    return [r[0] for r in rows]


def stats_by_country() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("""
            SELECT
                supplier_country    AS country,
                currency,
                COUNT(*)            AS invoice_count,
                SUM(net_amount)     AS total_net,
                SUM(vat_amount)     AS total_vat,
                SUM(gross_amount)   AS total_gross
            FROM invoices
            GROUP BY supplier_country, currency
            ORDER BY invoice_count DESC
        """).fetchall()


def stats_by_tx_type() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("""
            SELECT transaction_type, transaction_scope,
                   COUNT(*) AS invoice_count,
                   SUM(net_amount) AS total_net,
                   SUM(vat_amount) AS total_vat
            FROM invoices
            GROUP BY transaction_type, transaction_scope
            ORDER BY invoice_count DESC
        """).fetchall()


def stats_by_vat_treatment() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("""
            SELECT vat_treatment,
                   COUNT(*) AS invoice_count,
                   SUM(net_amount) AS total_net,
                   SUM(vat_amount) AS total_vat
            FROM invoices
            GROUP BY vat_treatment
            ORDER BY invoice_count DESC
        """).fetchall()


def get_api_logs(limit: int = 200) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM api_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()


# ── internal ──────────────────────────────────────────────────────────────────

def _build_where(
    *,
    country=None, date_from=None, date_to=None,
    transaction_type=None, transaction_scope=None,
    vat_treatment=None, description=None,
    **_,
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if country:
        conditions.append(
            "(supplier_country = ? OR customer_country = ? OR reporting_country = ?)"
        )
        params.extend([country, country, country])
    if date_from:
        conditions.append("invoice_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("invoice_date <= ?")
        params.append(date_to)
    if transaction_type:
        conditions.append("transaction_type = ?")
        params.append(transaction_type)
    if transaction_scope:
        conditions.append("transaction_scope = ?")
        params.append(transaction_scope)
    if vat_treatment:
        conditions.append("vat_treatment = ?")
        params.append(vat_treatment)
    if description:
        conditions.append(
            "invoice_id IN (SELECT DISTINCT invoice_id FROM line_items "
            "WHERE LOWER(description) LIKE ?)"
        )
        params.append(f"%{description.lower()}%")

    return conditions, params
