"""Parse UBL 2.1 XML e-invoices into Invoice dataclass.

Tested against the Ireland demo dataset (UBL 2.1, EN 16931-compliant).
VAT rate per line is read from cac:Item/cac:ClassifiedTaxCategory/cbc:Percent.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from lib.models import Invoice, LineItem

_NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

# Map UBL country sub-entity strings to ISO-2 codes
_COUNTRY_MAP = {
    "ireland": "IE", "germany": "DE", "france": "FR",
    "belgium": "BE", "netherlands": "NL", "spain": "ES",
    "italy": "IT", "portugal": "PT", "poland": "PL",
}


def parse_xml(file_bytes: bytes, filename: str = "") -> Invoice:
    """Parse a UBL 2.1 XML e-invoice and return an Invoice dataclass."""
    root = ET.fromstring(file_bytes)
    return _parse_ubl(root, filename)


def _text(el: ET.Element | None) -> str:
    return el.text.strip() if el is not None and el.text else ""


def _float(el: ET.Element | None, default: float = 0.0) -> float:
    try:
        return float(_text(el)) if el is not None else default
    except ValueError:
        return default


def _parse_ubl(root: ET.Element, filename: str) -> Invoice:
    def find(path: str) -> ET.Element | None:
        return root.find(path, _NS)

    invoice_number = _text(find("cbc:ID"))
    invoice_date   = _text(find("cbc:IssueDate"))
    currency       = _text(find("cbc:DocumentCurrencyCode")) or "EUR"

    supplier_name = _text(find(
        ".//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name"
    ))
    supplier_vat = _text(find(
        ".//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
    ))
    # Country comes as plain text ("Ireland") — normalise to ISO-2
    country_raw = _text(find(
        ".//cac:AccountingSupplierParty/cac:Party/cac:PostalAddress/cbc:CountrySubentity"
    ))
    supplier_country = _COUNTRY_MAP.get(country_raw.lower(), country_raw[:2].upper() if country_raw else "")

    customer_name = _text(find(
        ".//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name"
    ))

    line_items: list[LineItem] = []
    for line in root.findall(".//cac:InvoiceLine", _NS):
        item_id     = _text(line.find("cbc:ID", _NS)) or str(len(line_items) + 1)
        description = _text(
            line.find(".//cac:Item/cbc:Description", _NS)
            or line.find(".//cac:Item/cbc:Name", _NS)
        )
        quantity   = _float(line.find("cbc:InvoicedQuantity", _NS), 1.0)
        unit_price = _float(line.find(".//cac:Price/cbc:PriceAmount", _NS))
        line_ext   = _float(line.find("cbc:LineExtensionAmount", _NS),
                            unit_price * quantity)

        # VAT rate is on the line item itself (ClassifiedTaxCategory)
        vat_pct_el = line.find(".//cac:Item/cac:ClassifiedTaxCategory/cbc:Percent", _NS)
        vat_rate   = _float(vat_pct_el) / 100.0   # e.g. 23.0 → 0.23

        vat_amount      = round(line_ext * vat_rate, 2)
        total_incl_vat  = round(line_ext + vat_amount, 2)

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
