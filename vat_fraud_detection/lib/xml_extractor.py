"""Flexible XML invoice extraction pipeline.

Extraction strategy (in order):
  1. Format detection  — sniff root tag / namespaces.
  2. Rule-based parser — fast, deterministic XPath for known formats
                         (UBL 2.1, ZUGFeRD / Factur-X CII).
  3. LLM fallback      — if rules yield no line items or the format is unknown,
                         send raw XML to LM Studio for best-effort extraction.
  4. LLM enrichment    — always call LM Studio to classify each line item into
                         a product_category useful for VAT legislation lookup.

LM Studio is accessed via its OpenAI-compatible local API.
Configure via environment variables:
  LM_STUDIO_BASE_URL  (default: http://localhost:1234/v1)
  LM_STUDIO_MODEL     (default: mistralai/mistral-7b-instruct-v0.3)
"""
from __future__ import annotations

import json
import logging
import os
import xml.etree.ElementTree as ET
from typing import Callable

from lib.models import Invoice, LineItem

log = logging.getLogger(__name__)

# ── LM Studio config ──────────────────────────────────────────────────────────
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL    = os.getenv("LM_STUDIO_MODEL", "mistralai/mistral-7b-instruct-v0.3")
_LM_API_KEY        = "lm-studio"

# ── Known format namespace identifiers ───────────────────────────────────────
_UBL_NS     = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
_ZUGFERD_NS = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"

# ── UBL 2.1 namespace prefixes ────────────────────────────────────────────────
_UBL = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

# ── ZUGFeRD / Factur-X namespace prefixes ─────────────────────────────────────
_CII = {
    "rsm": _ZUGFERD_NS,
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}

_COUNTRY_MAP = {
    "ireland": "IE", "germany": "DE", "france": "FR",
    "belgium": "BE", "netherlands": "NL", "spain": "ES",
    "italy": "IT",  "portugal": "PT", "poland": "PL",
}


# ── XML helpers ───────────────────────────────────────────────────────────────

def _text(el: ET.Element | None) -> str:
    return el.text.strip() if el is not None and el.text else ""


def _float(el: ET.Element | None, default: float = 0.0) -> float:
    try:
        return float(_text(el)) if el is not None else default
    except ValueError:
        return default


# ── Format detection ──────────────────────────────────────────────────────────

def _detect_format(root: ET.Element) -> str:
    """Return 'ubl21', 'zugferd', or 'unknown'."""
    tag = root.tag
    if _UBL_NS in tag:
        return "ubl21"
    if _ZUGFERD_NS in tag:
        return "zugferd"
    # Check namespace declarations in root attributes
    for v in root.attrib.values():
        if _UBL_NS in v:
            return "ubl21"
        if _ZUGFERD_NS in v:
            return "zugferd"
    return "unknown"


# ── Rule-based parsers ────────────────────────────────────────────────────────

def _parse_ubl21(root: ET.Element, filename: str) -> Invoice:
    """Parse a UBL 2.1 / EN 16931 XML invoice."""
    def find(path: str) -> ET.Element | None:
        return root.find(path, _UBL)

    invoice_number = _text(find("cbc:ID"))
    invoice_date   = _text(find("cbc:IssueDate"))
    currency       = _text(find("cbc:DocumentCurrencyCode")) or "EUR"

    supplier_name = _text(find(
        ".//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name"
    ))
    supplier_vat = _text(find(
        ".//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
    ))
    country_raw = _text(find(
        ".//cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:CountrySubentity"
    ))
    supplier_country = _COUNTRY_MAP.get(
        country_raw.lower(),
        country_raw[:2].upper() if country_raw else "",
    )
    customer_name = _text(find(
        ".//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name"
    ))

    line_items: list[LineItem] = []
    for line in root.findall(".//cac:InvoiceLine", _UBL):
        item_id = _text(line.find("cbc:ID", _UBL)) or str(len(line_items) + 1)
        description = _text(
            line.find(".//cac:Item/cbc:Description", _UBL)
            or line.find(".//cac:Item/cbc:Name", _UBL)
        )
        quantity   = _float(line.find("cbc:InvoicedQuantity", _UBL), 1.0)
        unit_price = _float(line.find(".//cac:Price/cbc:PriceAmount", _UBL))
        line_ext   = _float(
            line.find("cbc:LineExtensionAmount", _UBL),
            unit_price * quantity,
        )
        vat_rate = _float(
            line.find(".//cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", _UBL)
        ) / 100.0
        vat_amount     = round(line_ext * vat_rate, 2)
        total_incl_vat = round(line_ext + vat_amount, 2)

        line_items.append(LineItem(
            id=item_id,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            vat_rate_applied=vat_rate,
            vat_amount=vat_amount,
            total_incl_vat=total_incl_vat,
        ))

    return Invoice(
        source_file=filename,
        supplier_name=supplier_name,
        supplier_vat_number=supplier_vat,
        customer_name=customer_name,
        supplier_country=supplier_country,
        invoice_date=invoice_date,
        invoice_number=invoice_number,
        currency=currency,
        line_items=line_items,
    )


def _parse_zugferd(root: ET.Element, filename: str) -> Invoice:
    """Parse a ZUGFeRD / Factur-X Cross Industry Invoice (CII) XML."""
    def find(path: str) -> ET.Element | None:
        return root.find(path, _CII)

    invoice_number = _text(find(".//ram:ExchangedDocument/ram:ID"))
    invoice_date   = _text(find(
        ".//ram:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString"
    ))
    currency = _text(find(
        ".//ram:SpecifiedSupplyChainTradeSettlement/ram:InvoiceCurrencyCode"
    )) or "EUR"

    supplier_name    = _text(find(".//ram:SellerTradeParty/ram:Name"))
    supplier_vat     = _text(find(
        ".//ram:SellerTradeParty/ram:SpecifiedTaxRegistration/ram:ID"
    ))
    supplier_country = _text(find(
        ".//ram:SellerTradeParty/ram:PostalTradeAddress/ram:CountryID"
    )).upper()
    customer_name = _text(find(".//ram:BuyerTradeParty/ram:Name"))

    line_items: list[LineItem] = []
    for line in root.findall(".//ram:IncludedSupplyChainTradeLineItem", _CII):
        item_id = _text(
            line.find(".//ram:AssociatedDocumentLineDocument/ram:LineID", _CII)
        ) or str(len(line_items) + 1)
        description = _text(line.find(".//ram:SpecifiedTradeProduct/ram:Name", _CII))
        quantity    = _float(
            line.find(".//ram:SpecifiedLineTradeDelivery/ram:BilledQuantity", _CII),
            1.0,
        )
        unit_price = _float(line.find(
            ".//ram:SpecifiedLineTradeAgreement"
            "/ram:NetPriceProductTradePrice/ram:ChargeAmount",
            _CII,
        ))
        line_ext = _float(line.find(
            ".//ram:SpecifiedLineTradeSettlement"
            "/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount",
            _CII,
        ), unit_price * quantity)
        vat_rate = _float(line.find(
            ".//ram:SpecifiedLineTradeSettlement"
            "/ram:ApplicableTradeTax/ram:RateApplicablePercent",
            _CII,
        )) / 100.0
        vat_amount     = round(line_ext * vat_rate, 2)
        total_incl_vat = round(line_ext + vat_amount, 2)

        line_items.append(LineItem(
            id=item_id,
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            vat_rate_applied=vat_rate,
            vat_amount=vat_amount,
            total_incl_vat=total_incl_vat,
        ))

    return Invoice(
        source_file=filename,
        supplier_name=supplier_name,
        supplier_vat_number=supplier_vat,
        customer_name=customer_name,
        supplier_country=supplier_country,
        invoice_date=invoice_date,
        invoice_number=invoice_number,
        currency=currency,
        line_items=line_items,
    )


# Registry: add new rule-based parsers here as new formats are encountered
_RULE_PARSERS: dict[str, Callable[[ET.Element, str], Invoice]] = {
    "ubl21":   _parse_ubl21,
    "zugferd": _parse_zugferd,
}


# ── LM Studio helpers ─────────────────────────────────────────────────────────

def _lm_client():
    from openai import OpenAI
    return OpenAI(base_url=LM_STUDIO_BASE_URL, api_key=_LM_API_KEY)


_FALLBACK_SYSTEM = """\
You are an invoice data extraction assistant.
Extract structured information from the XML invoice and return ONLY a valid JSON object — \
no explanation, no markdown fences.

Schema:
{
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "supplier_name": "string",
  "supplier_vat_number": "string",
  "customer_name": "string",
  "supplier_country": "ISO-2 country code e.g. IE",
  "currency": "string",
  "line_items": [
    {
      "id": "string",
      "description": "product or service name",
      "quantity": 1.0,
      "unit_price": 0.0,
      "vat_rate_applied": 0.23,
      "vat_amount": 0.0,
      "total_incl_vat": 0.0
    }
  ]
}

Rules:
- vat_rate_applied is a decimal fraction (0.23 for 23%, 0.09 for 9%, 0.0 for exempt/zero-rated).
- Each invoice line must be a separate entry in line_items.
- If a field is not present use empty string or 0."""

_ENRICH_SYSTEM = """\
You are a VAT classification assistant.
For each invoice line item, assign a product_category that describes the item \
for Irish VAT purposes.

Use specific categories such as:
  Food & Beverages, Catering Services, Electronic Publications, Print Publications,
  Medical Devices, Pharmaceuticals, Children's Clothing, Adult Clothing,
  Professional Services, Construction, Financial Services, Telecommunications,
  Energy, Passenger Transport, Tourism & Hospitality, Other.

Return ONLY a valid JSON array — no explanation, no markdown fences.
Each element: {"id": "...", "product_category": "..."}"""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _llm_extract(xml_text: str, filename: str) -> Invoice:
    """Call LM Studio to extract invoice fields from raw XML text."""
    client = _lm_client()
    # Mistral-family templates reject "system" role — merge into user.
    merged_user = f"{_FALLBACK_SYSTEM}\n\n-----\n{xml_text[:12_000]}"
    try:
        resp = client.chat.completions.create(
            model=LM_STUDIO_MODEL,
            messages=[{"role": "user", "content": merged_user}],
            temperature=0.0,
            max_tokens=2048,
        )
        data = json.loads(_strip_fences(resp.choices[0].message.content))
    except Exception as exc:
        log.warning("LLM extraction failed for %s: %s", filename, exc)
        return Invoice(source_file=filename)

    line_items = [
        LineItem(
            id=str(li.get("id", i)),
            description=li.get("description", ""),
            quantity=float(li.get("quantity", 1)),
            unit_price=float(li.get("unit_price", 0)),
            vat_rate_applied=float(li.get("vat_rate_applied", 0)),
            vat_amount=float(li.get("vat_amount", 0)),
            total_incl_vat=float(li.get("total_incl_vat", 0)),
        )
        for i, li in enumerate(data.get("line_items", []))
    ]
    return Invoice(
        source_file=filename,
        invoice_number=data.get("invoice_number", ""),
        invoice_date=data.get("invoice_date", ""),
        supplier_name=data.get("supplier_name", ""),
        supplier_vat_number=data.get("supplier_vat_number", ""),
        customer_name=data.get("customer_name", ""),
        supplier_country=data.get("supplier_country", ""),
        currency=data.get("currency", "EUR"),
        line_items=line_items,
    )


def _llm_enrich_categories(line_items: list[LineItem]) -> None:
    """Classify each line item into a product_category (in-place) via LM Studio."""
    if not line_items:
        return
    payload = json.dumps([{"id": li.id, "description": li.description} for li in line_items])
    client = _lm_client()
    # Mistral-family templates reject "system" role — merge into user.
    merged_user = f"{_ENRICH_SYSTEM}\n\n-----\n{payload}"
    try:
        resp = client.chat.completions.create(
            model=LM_STUDIO_MODEL,
            messages=[{"role": "user", "content": merged_user}],
            temperature=0.0,
            max_tokens=512,
        )
        categories: dict[str, str] = {
            str(item["id"]): item["product_category"]
            for item in json.loads(_strip_fences(resp.choices[0].message.content))
        }
        for li in line_items:
            li.product_category = categories.get(str(li.id), li.product_category)
    except Exception as exc:
        log.warning("LLM category enrichment failed: %s", exc)


# ── Public entry point ────────────────────────────────────────────────────────

def extract_from_xml(file_bytes: bytes, filename: str = "") -> Invoice:
    """Parse an XML invoice file and return a fully populated Invoice.

    Pipeline:
      1. Parse XML + detect format.
      2. Run rule-based parser if format is known.
      3. Fall back to LM Studio if format is unknown or no line items found.
      4. Enrich product_category for all line items via LM Studio.
    """
    xml_text = file_bytes.decode("utf-8", errors="replace")

    # Step 1 — XML parse
    try:
        root = ET.fromstring(file_bytes)
    except ET.ParseError as exc:
        log.warning("XML parse error in %s: %s — using LLM fallback", filename, exc)
        invoice = _llm_extract(xml_text, filename)
        _llm_enrich_categories(invoice.line_items)
        invoice.raw_text = xml_text
        return invoice

    fmt = _detect_format(root)
    log.debug("Detected XML format '%s' for %s", fmt, filename)

    # Step 2 — rule-based extraction
    invoice: Invoice | None = None
    if fmt in _RULE_PARSERS:
        try:
            invoice = _RULE_PARSERS[fmt](root, filename)
            log.debug("Rule-based extraction: %d line item(s)", len(invoice.line_items))
        except Exception as exc:
            log.warning("Rule-based parser failed for %s: %s", filename, exc)

    # Step 3 — LLM fallback
    if invoice is None or not invoice.line_items:
        log.info("Falling back to LLM for %s (format=%s)", filename, fmt)
        invoice = _llm_extract(xml_text, filename)

    invoice.raw_text = xml_text

    # Step 4 — LLM enrichment
    _llm_enrich_categories(invoice.line_items)

    return invoice
