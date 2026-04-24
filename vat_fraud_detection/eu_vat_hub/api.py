"""EU VAT Hub — FastAPI REST API (port 8503).

Serves factual invoice data only. Risk assessment is the member states' responsibility.

Start with:
    uvicorn api:app --port 8503 --reload
from the eu_vat_hub/ directory.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent))

from lib.database import (
    count_invoices,
    get_api_logs,
    get_countries,
    get_invoice,
    get_line_items,
    get_suppliers,
    init_db,
    query_invoices,
    stats_by_country,
    stats_by_tx_type,
    stats_by_vat_treatment,
    total_count,
)
from lib.logging_middleware import ApiLoggingMiddleware
from lib.models import (
    ApiLogEntry,
    CountryStat,
    HealthResponse,
    InvoiceDetail,
    InvoiceListResponse,
    InvoiceSummary,
    LineItemSummary,
    TxTypeStat,
    VatTreatmentStat,
)
from lib.seeder import seed_if_empty


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    added = seed_if_empty()
    if added:
        print(f"[EU VAT Hub] Seeded {added:,} invoice records.")
    else:
        print(f"[EU VAT Hub] DB ready — {total_count():,} records.")
    yield


app = FastAPI(
    title="EU VAT Hub API",
    description=(
        "Central EU VAT invoice repository. "
        "Stores factual invoice data submitted by member states. "
        "Risk scoring is performed by each country's own system."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Records-Returned"],
)
app.add_middleware(ApiLoggingMiddleware)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health():
    return HealthResponse(status="ok", db_records=total_count())


# ── Invoices ──────────────────────────────────────────────────────────────────

def _row_to_summary(row) -> InvoiceSummary:
    return InvoiceSummary(
        invoice_id=row["invoice_id"],
        invoice_number=row["invoice_number"],
        invoice_date=row["invoice_date"],
        supplier_name=row["supplier_name"],
        supplier_vat=row["supplier_vat"],
        supplier_country=row["supplier_country"],
        customer_name=row["customer_name"],
        customer_vat=row["customer_vat"],
        customer_country=row["customer_country"],
        net_amount=row["net_amount"],
        vat_amount=row["vat_amount"],
        gross_amount=row["gross_amount"],
        currency=row["currency"],
        transaction_type=row["transaction_type"],
        transaction_scope=row["transaction_scope"],
        vat_treatment=row["vat_treatment"],
        vat_rate_applied=row["vat_rate_applied"],
        reporting_country=row["reporting_country"],
        created_at=row["created_at"],
    )


@app.get("/api/v1/invoices", response_model=InvoiceListResponse, tags=["invoices"])
def list_invoices(
    response: Response,
    country: str | None = Query(None, description="ISO-2 code — matches supplier, customer, or reporting country"),
    date_from: str | None = Query(None, description="YYYY-MM-DD inclusive lower bound"),
    date_to:   str | None = Query(None, description="YYYY-MM-DD inclusive upper bound"),
    transaction_type:  str | None = Query(None, description="B2B | B2C"),
    transaction_scope: str | None = Query(None, description="domestic | intra_EU | extra_EU"),
    vat_treatment: str | None = Query(None, description="standard | reduced | zero | exempt | reverse_charge"),
    description: str | None = Query(None, description="Substring search in line-item descriptions"),
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0,   ge=0),
):
    kwargs = dict(
        country=country, date_from=date_from, date_to=date_to,
        transaction_type=transaction_type, transaction_scope=transaction_scope,
        vat_treatment=vat_treatment, description=description,
    )
    total = count_invoices(**kwargs)
    rows  = query_invoices(**kwargs, limit=limit, offset=offset)
    items = [_row_to_summary(r) for r in rows]
    response.headers["X-Records-Returned"] = str(len(items))
    return InvoiceListResponse(total=total, items=items)


@app.get("/api/v1/invoices/{invoice_id}", response_model=InvoiceDetail, tags=["invoices"])
def get_invoice_detail(invoice_id: str, response: Response):
    row = get_invoice(invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    li_rows = get_line_items(invoice_id)
    line_items = [
        LineItemSummary(
            description=li["description"],
            product_category=li["product_category"],
            quantity=li["quantity"],
            unit_price=li["unit_price"],
            vat_rate_applied=li["vat_rate_applied"],
            net_amount=li["net_amount"],
            vat_amount=li["vat_amount"],
        )
        for li in li_rows
    ]
    response.headers["X-Records-Returned"] = "1"
    return InvoiceDetail(**_row_to_summary(row).model_dump(), line_items=line_items)


# ── Reference data ────────────────────────────────────────────────────────────

@app.get("/api/v1/countries", response_model=list[str], tags=["reference"])
def list_countries(response: Response):
    result = get_countries()
    response.headers["X-Records-Returned"] = str(len(result))
    return result


@app.get("/api/v1/suppliers", response_model=list[str], tags=["reference"])
def list_suppliers(response: Response, country: str | None = Query(None)):
    result = get_suppliers(country=country)
    response.headers["X-Records-Returned"] = str(len(result))
    return result


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/stats/by-country", response_model=list[CountryStat], tags=["analytics"])
def stats_country(response: Response):
    rows = stats_by_country()
    result = [
        CountryStat(
            country=r["country"], currency=r["currency"],
            invoice_count=r["invoice_count"],
            total_net=r["total_net"] or 0,
            total_vat=r["total_vat"] or 0,
            total_gross=r["total_gross"] or 0,
        )
        for r in rows
    ]
    response.headers["X-Records-Returned"] = str(len(result))
    return result


@app.get("/api/v1/stats/by-transaction-type", response_model=list[TxTypeStat], tags=["analytics"])
def stats_tx_type(response: Response):
    rows = stats_by_tx_type()
    result = [
        TxTypeStat(
            transaction_type=r["transaction_type"],
            transaction_scope=r["transaction_scope"],
            invoice_count=r["invoice_count"],
            total_net=r["total_net"] or 0,
            total_vat=r["total_vat"] or 0,
        )
        for r in rows
    ]
    response.headers["X-Records-Returned"] = str(len(result))
    return result


@app.get("/api/v1/stats/by-vat-treatment", response_model=list[VatTreatmentStat], tags=["analytics"])
def stats_vat_treatment(response: Response):
    rows = stats_by_vat_treatment()
    result = [
        VatTreatmentStat(
            vat_treatment=r["vat_treatment"],
            invoice_count=r["invoice_count"],
            total_net=r["total_net"] or 0,
            total_vat=r["total_vat"] or 0,
        )
        for r in rows
    ]
    response.headers["X-Records-Returned"] = str(len(result))
    return result


# ── Activity log ──────────────────────────────────────────────────────────────

@app.get("/api/v1/logs", response_model=list[ApiLogEntry], tags=["activity"])
def activity_logs(response: Response, limit: int = Query(200, ge=1, le=1000)):
    rows = get_api_logs(limit=limit)
    result = [
        ApiLogEntry(
            id=r["id"], timestamp=r["timestamp"], method=r["method"],
            endpoint=r["endpoint"], client_country=r["client_country"],
            status_code=r["status_code"], response_time_ms=r["response_time_ms"],
            records_returned=r["records_returned"],
        )
        for r in rows
    ]
    response.headers["X-Records-Returned"] = str(len(result))
    return result
