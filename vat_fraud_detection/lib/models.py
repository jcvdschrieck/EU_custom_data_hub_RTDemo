"""Core data models for the VAT fraud detection pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
import uuid

@dataclass
class LineItem:
    id: str
    description: str
    quantity: float
    unit_price: float          # excl. VAT
    vat_rate_applied: float    # e.g. 0.21 for 21%
    vat_amount: float
    total_incl_vat: float
    product_category: str = ""  # extracted hint for legislation lookup

@dataclass
class Invoice:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_file: str = ""
    supplier_name: str = ""
    supplier_vat_number: str = ""
    customer_name: str = ""
    supplier_country: str = ""       # ISO-2, e.g. "IN" or "CN"  (where the goods originate)
    destination_country: str = ""    # ISO-2, e.g. "IE"           (VAT jurisdiction that applies)
    invoice_date: str = ""
    invoice_number: str = ""
    currency: str = "EUR"
    line_items: list[LineItem] = field(default_factory=list)
    raw_text: str = ""          # original OCR/XML text before extraction

@dataclass
class LegislationRef:
    """A single source document reference returned by the analyser."""
    source: str    # human-readable document name
    url: str       # source URL (empty string if unavailable)
    section: str   # section or heading within the document
    ref: str = ""       # [1], [2], … as cited in the reasoning
    page: str = ""      # page number(s), e.g. "42" or "42–44"
    paragraph: str = "" # verbatim legislation excerpt used as evidence

@dataclass
class VATVerdict:
    line_item_id: str
    applied_rate: float
    expected_rate: float | None        # None if legislation is ambiguous
    verdict: Literal["correct", "incorrect", "uncertain"]
    reasoning: str
    legislation_refs: list[LegislationRef] = field(default_factory=list)

@dataclass
class AnalysisResult:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    invoice: Invoice = field(default_factory=Invoice)
    verdicts: list[VATVerdict] = field(default_factory=list)
    overall_verdict: Literal["correct", "incorrect", "uncertain"] = "uncertain"
    analysed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    model_used: str = ""

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AnalysisResult":
        # Reconstruct nested dataclasses from dict
        line_items = [LineItem(**li) for li in d["invoice"].pop("line_items", [])]
        invoice = Invoice(**d["invoice"], line_items=line_items)
        verdicts = [
            VATVerdict(
                **{k: v for k, v in vd.items() if k != "legislation_refs"},
                legislation_refs=[
                    LegislationRef(**r) if isinstance(r, dict)
                    else LegislationRef(source=str(r), url="", section="")
                    for r in vd.get("legislation_refs", [])
                ],
            )
            for vd in d.get("verdicts", [])
        ]
        d.pop("invoice")
        d.pop("verdicts", None)
        return AnalysisResult(invoice=invoice, verdicts=verdicts, **d)
