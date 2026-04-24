"""Pydantic response models — factual invoice data only, no risk scoring."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LineItemSummary(BaseModel):
    description: str
    product_category: str
    quantity: float
    unit_price: float
    vat_rate_applied: float
    net_amount: float
    vat_amount: float


class InvoiceSummary(BaseModel):
    invoice_id: str
    invoice_number: str
    invoice_date: str
    supplier_name: str
    supplier_vat: str | None
    supplier_country: str
    customer_name: str
    customer_vat: str | None
    customer_country: str
    net_amount: float
    vat_amount: float
    gross_amount: float
    currency: str
    transaction_type: Literal["B2B", "B2C"]
    transaction_scope: Literal["domestic", "intra_EU", "extra_EU"]
    vat_treatment: Literal["standard", "reduced", "zero", "exempt", "reverse_charge"]
    vat_rate_applied: float
    reporting_country: str
    created_at: str


class InvoiceDetail(InvoiceSummary):
    line_items: list[LineItemSummary]


class InvoiceListResponse(BaseModel):
    total: int
    items: list[InvoiceSummary]


class CountryStat(BaseModel):
    country: str
    currency: str
    invoice_count: int
    total_net: float
    total_vat: float
    total_gross: float


class TxTypeStat(BaseModel):
    transaction_type: str
    transaction_scope: str
    invoice_count: int
    total_net: float
    total_vat: float


class VatTreatmentStat(BaseModel):
    vat_treatment: str
    invoice_count: int
    total_net: float
    total_vat: float


class ApiLogEntry(BaseModel):
    id: int
    timestamp: str
    method: str
    endpoint: str
    client_country: str | None
    status_code: int
    response_time_ms: float
    records_returned: int


class HealthResponse(BaseModel):
    status: str
    db_records: int
