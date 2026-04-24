"""HTTP client for querying the EU VAT Hub API.

All outgoing requests include X-Client-Country: IE and are logged to
data/eu_query_log.db for the local activity audit trail.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

EU_HUB_BASE_URL = "http://localhost:8503"

# Records in the EU Hub with date > CUTOFF are the "increment" Ireland hasn't processed yet
IE_CUTOFF_DATE = "2026-03-25"
IE_INCREMENT_FROM = "2026-03-26"   # day after cutoff (EU query uses >= this date)

_LOG_PATH = Path(__file__).parent.parent / "data" / "eu_query_log.db"

_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS eu_query_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,
    method           TEXT NOT NULL,
    endpoint         TEXT NOT NULL,
    status_code      INTEGER,
    response_time_ms REAL NOT NULL,
    records_returned INTEGER NOT NULL DEFAULT 0,
    success          INTEGER NOT NULL DEFAULT 1,
    error_message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_eq_ts ON eu_query_log(timestamp);
"""


def _init_log_db() -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_LOG_PATH) as c:
        for stmt in _LOG_SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                c.execute(s)


def _write_log(*, method, endpoint, status_code, response_time_ms,
               records_returned, success, error_message=None):
    _init_log_db()
    with sqlite3.connect(_LOG_PATH) as c:
        c.execute(
            "INSERT INTO eu_query_log "
            "(timestamp, method, endpoint, status_code, response_time_ms, "
            "records_returned, success, error_message) VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), method, endpoint,
             status_code, round(response_time_ms, 1), records_returned,
             1 if success else 0, error_message),
        )


def _request(method: str, path: str, **params):
    clean = {k: v for k, v in params.items() if v is not None}
    start = time.perf_counter()
    try:
        with httpx.Client(
            base_url=EU_HUB_BASE_URL,
            headers={"X-Client-Country": "IE"},
            timeout=15.0,
        ) as client:
            resp = client.request(method, path, params=clean)
        elapsed = (time.perf_counter() - start) * 1000
        records = int(resp.headers.get("X-Records-Returned", 0))
        _write_log(method=method, endpoint=path, status_code=resp.status_code,
                   response_time_ms=elapsed, records_returned=records,
                   success=resp.status_code < 400)
        return resp.json()
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        _write_log(method=method, endpoint=path, status_code=None,
                   response_time_ms=elapsed, records_returned=0,
                   success=False, error_message=str(exc))
        return None


# ── Public query API ──────────────────────────────────────────────────────────

def health_check() -> bool:
    result = _request("GET", "/health")
    return isinstance(result, dict) and result.get("status") == "ok"


def list_invoices(
    *,
    country: str | None = None,
    date_from: str | None = None,
    date_to:   str | None = None,
    transaction_type:  str | None = None,
    transaction_scope: str | None = None,
    vat_treatment:     str | None = None,
    description:       str | None = None,
    limit:  int = 200,
    offset: int = 0,
) -> dict:
    result = _request(
        "GET", "/api/v1/invoices",
        country=country, date_from=date_from, date_to=date_to,
        transaction_type=transaction_type, transaction_scope=transaction_scope,
        vat_treatment=vat_treatment, description=description,
        limit=limit, offset=offset,
    )
    return result or {"total": 0, "items": []}


def fetch_increment(limit: int = 500) -> dict:
    """Fetch Irish invoices in the EU Hub that post-date the Irish DB cutoff."""
    return list_invoices(
        country=None,       # we filter via reporting_country in the query
        date_from=IE_INCREMENT_FROM,
        limit=limit,
    )


def get_invoice(invoice_id: str) -> dict | None:
    return _request("GET", f"/api/v1/invoices/{invoice_id}")


def stats_by_country() -> list[dict]:
    result = _request("GET", "/api/v1/stats/by-country")
    return result if isinstance(result, list) else []


def get_hub_logs(limit: int = 100) -> list[dict]:
    result = _request("GET", "/api/v1/logs", limit=limit)
    return result if isinstance(result, list) else []


def get_local_logs(limit: int = 200) -> list[dict]:
    _init_log_db()
    with sqlite3.connect(_LOG_PATH) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM eu_query_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def clear_local_logs() -> None:
    _init_log_db()
    with sqlite3.connect(_LOG_PATH) as c:
        c.execute("DELETE FROM eu_query_log")


# ── Conversion: EU Hub invoice → Ireland Invoice model ────────────────────────

def eu_detail_to_invoice(detail: dict):
    """Convert a full EU Hub InvoiceDetail dict to an Ireland Invoice model object."""
    from lib.models import Invoice, LineItem

    line_items = []
    for i, li in enumerate(detail.get("line_items", []), 1):
        net    = li.get("net_amount", 0.0)
        vat    = li.get("vat_amount", 0.0)
        qty    = li.get("quantity", 1.0)
        price  = li.get("unit_price", 0.0)
        rate   = li.get("vat_rate_applied", 0.0)
        line_items.append(LineItem(
            id=str(i),
            description=li.get("description", ""),
            quantity=qty,
            unit_price=price,
            vat_rate_applied=rate,
            vat_amount=vat,
            total_incl_vat=round(net + vat, 2),
            product_category=li.get("product_category", ""),
        ))

    return Invoice(
        id=detail["invoice_id"],
        source_file=detail["invoice_number"],
        supplier_name=detail.get("supplier_name", ""),
        supplier_vat_number=detail.get("supplier_vat") or "",
        customer_name=detail.get("customer_name", ""),
        supplier_country=detail.get("supplier_country", "IE"),
        invoice_date=detail.get("invoice_date", ""),
        invoice_number=detail.get("invoice_number", ""),
        currency=detail.get("currency", "EUR"),
        line_items=line_items,
        raw_text="",
    )
