"""SQLite-backed activity log for LLM VAT analysis calls (Ireland app)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_LOG_PATH = Path(__file__).parent.parent / "data" / "analysis_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         TEXT NOT NULL,
    invoice_number    TEXT,
    supplier_name     TEXT,
    model_used        TEXT,
    line_items_count  INTEGER NOT NULL DEFAULT 0,
    overall_verdict   TEXT,
    response_time_ms  REAL NOT NULL DEFAULT 0,
    success           INTEGER NOT NULL DEFAULT 1,
    error_message     TEXT
);
CREATE INDEX IF NOT EXISTS idx_al_ts ON analysis_log(timestamp);
"""


def _init() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_LOG_PATH) as c:
        for stmt in _SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                c.execute(s)


def write_log(
    *,
    invoice_number: str,
    supplier_name: str,
    model_used: str,
    line_items_count: int,
    overall_verdict: str | None,
    response_time_ms: float,
    success: bool = True,
    error_message: str | None = None,
) -> None:
    _init()
    with sqlite3.connect(_LOG_PATH) as c:
        c.execute(
            "INSERT INTO analysis_log "
            "(timestamp, invoice_number, supplier_name, model_used, line_items_count, "
            "overall_verdict, response_time_ms, success, error_message) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                invoice_number,
                supplier_name,
                model_used,
                line_items_count,
                overall_verdict,
                round(response_time_ms, 1),
                1 if success else 0,
                error_message,
            ),
        )


def get_logs(limit: int = 200) -> list[dict]:
    _init()
    with sqlite3.connect(_LOG_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM analysis_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def clear_logs() -> None:
    _init()
    with sqlite3.connect(_LOG_PATH) as c:
        c.execute("DELETE FROM analysis_log")
