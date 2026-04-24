"""SQLite backend for fast, filtered querying of pre-scored invoice records.

Schema
------
invoices   — one row per AnalysisResult; stores pre-computed risk scores and
             the full serialised result JSON for drill-down reconstruction.
line_items — one row per line item; enables efficient description-text search.

All date values are stored as ISO strings (YYYY-MM-DD) so SQLite's text
collation produces correct chronological ORDER BY / BETWEEN results.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("data/vat_audit.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    result_id           TEXT PRIMARY KEY,
    invoice_number      TEXT,
    invoice_date        TEXT,
    supplier_name       TEXT,
    supplier_vat        TEXT,
    customer_name       TEXT,
    overall_verdict     TEXT,
    analysed_at         TEXT,
    total_exposure      REAL    DEFAULT 0,
    materiality_score   REAL    DEFAULT 0,
    rule_severity_score REAL    DEFAULT 0,
    historical_score    REAL    DEFAULT 0,
    risk_score          REAL    DEFAULT 0,
    risk_tier           TEXT    DEFAULT 'LOW',
    n_incorrect         INTEGER DEFAULT 0,
    n_uncertain         INTEGER DEFAULT 0,
    n_correct           INTEGER DEFAULT 0,
    past_issue_count    INTEGER DEFAULT 0,
    result_json         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS line_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id        TEXT    NOT NULL REFERENCES invoices(result_id) ON DELETE CASCADE,
    description      TEXT,
    product_category TEXT,
    verdict          TEXT
);

CREATE INDEX IF NOT EXISTS idx_invoice_date     ON invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_supplier_name    ON invoices(supplier_name);
CREATE INDEX IF NOT EXISTS idx_risk_tier        ON invoices(risk_tier);
CREATE INDEX IF NOT EXISTS idx_risk_score       ON invoices(risk_score);
CREATE INDEX IF NOT EXISTS idx_overall_verdict  ON invoices(overall_verdict);
CREATE INDEX IF NOT EXISTS idx_li_result        ON line_items(result_id);
CREATE INDEX IF NOT EXISTS idx_li_description   ON line_items(description);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def init_db() -> None:
    """Create tables and indexes if they do not already exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        for stmt in _SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)


def upsert_scored_result(
    result_id: str,
    invoice_number: str,
    invoice_date: str,
    supplier_name: str,
    supplier_vat: str,
    customer_name: str,
    overall_verdict: str,
    analysed_at: str,
    total_exposure: float,
    materiality_score: float,
    rule_severity_score: float,
    historical_score: float,
    risk_score: float,
    risk_tier: str,
    n_incorrect: int,
    n_uncertain: int,
    n_correct: int,
    past_issue_count: int,
    result_dict: dict,
    line_items: list[dict],  # [{"description": str, "product_category": str, "verdict": str}]
) -> None:
    """Insert or replace a scored invoice record."""
    with _conn() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO invoices VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                result_id, invoice_number, invoice_date,
                supplier_name, supplier_vat, customer_name,
                overall_verdict, analysed_at,
                total_exposure, materiality_score, rule_severity_score,
                historical_score, risk_score, risk_tier,
                n_incorrect, n_uncertain, n_correct, past_issue_count,
                json.dumps(result_dict),
            ),
        )
        c.execute("DELETE FROM line_items WHERE result_id = ?", (result_id,))
        c.executemany(
            "INSERT INTO line_items (result_id, description, product_category, verdict) VALUES (?,?,?,?)",
            [
                (result_id, li.get("description", ""), li.get("product_category", ""), li.get("verdict", ""))
                for li in line_items
            ],
        )


def query_invoices(
    *,
    date_from: str | None = None,
    date_to:   str | None = None,
    suppliers: list[str] | None = None,
    tiers:     list[str] | None = None,
    min_score: float = 0,
    description: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[sqlite3.Row]:
    """Return scored invoice rows matching the given filters."""
    conditions, params = _build_where(
        date_from=date_from, date_to=date_to,
        suppliers=suppliers, tiers=tiers,
        min_score=min_score, description=description,
    )
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _conn() as c:
        return c.execute(
            f"SELECT * FROM invoices {where} "
            f"ORDER BY invoice_date DESC, risk_score DESC "
            f"LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()


def count_invoices(
    *,
    date_from: str | None = None,
    date_to:   str | None = None,
    suppliers: list[str] | None = None,
    tiers:     list[str] | None = None,
    min_score: float = 0,
    description: str | None = None,
) -> int:
    """Return the total number of rows matching the given filters."""
    conditions, params = _build_where(
        date_from=date_from, date_to=date_to,
        suppliers=suppliers, tiers=tiers,
        min_score=min_score, description=description,
    )
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _conn() as c:
        return c.execute(f"SELECT COUNT(*) FROM invoices {where}", params).fetchone()[0]


def get_result_json(result_id: str) -> dict | None:
    """Return the full serialised AnalysisResult dict for *result_id*, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT result_json FROM invoices WHERE result_id = ?", (result_id,)
        ).fetchone()
    return json.loads(row["result_json"]) if row else None


def get_suppliers() -> list[str]:
    """Return all distinct supplier names, sorted alphabetically."""
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT supplier_name FROM invoices WHERE supplier_name IS NOT NULL "
            "ORDER BY supplier_name"
        ).fetchall()
    return [r["supplier_name"] for r in rows]


def total_count() -> int:
    """Total number of records in the DB (no filters)."""
    with _conn() as c:
        return c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]


# ── internal ─────────────────────────────────────────────────────────────────

def _build_where(
    *,
    date_from, date_to, suppliers, tiers, min_score, description,
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if date_from:
        conditions.append("invoice_date >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("invoice_date <= ?")
        params.append(date_to)
    if suppliers:
        placeholders = ",".join("?" * len(suppliers))
        conditions.append(f"supplier_name IN ({placeholders})")
        params.extend(suppliers)
    if tiers:
        placeholders = ",".join("?" * len(tiers))
        conditions.append(f"risk_tier IN ({placeholders})")
        params.extend(tiers)
    if min_score and min_score > 0:
        conditions.append("risk_score >= ?")
        params.append(min_score)
    if description:
        conditions.append(
            "result_id IN (SELECT DISTINCT result_id FROM line_items "
            "WHERE LOWER(description) LIKE ?)"
        )
        params.append(f"%{description.lower()}%")

    return conditions, params
