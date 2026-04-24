"""Placeholder tests for lib.xml_parser."""
from __future__ import annotations
import pytest

# Minimal valid UBL 2.1 XML for testing
_MINIMAL_UBL = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>INV-001</cbc:ID>
  <cbc:IssueDate>2024-06-01</cbc:IssueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>ACME Corp</cbc:Name></cac:PartyName>
      <cac:PostalAddress>
        <cac:Country><cbc:IdentificationCode>BE</cbc:IdentificationCode></cac:Country>
      </cac:PostalAddress>
    </cac:Party>
  </cac:AccountingSupplierParty>
</Invoice>
"""


def test_parse_xml_returns_invoice():
    """parse_xml produces an Invoice for a minimal UBL document."""
    from lib.xml_parser import parse_xml
    from lib.models import Invoice

    invoice = parse_xml(_MINIMAL_UBL, "test_invoice.xml")
    assert isinstance(invoice, Invoice)
    assert invoice.invoice_number == "INV-001"
    assert invoice.invoice_date == "2024-06-01"
    assert invoice.supplier_name == "ACME Corp"
    assert invoice.supplier_country == "BE"
    assert invoice.currency == "EUR"


def test_parse_xml_no_line_items():
    """A UBL document with no InvoiceLines yields an empty line_items list."""
    from lib.xml_parser import parse_xml

    invoice = parse_xml(_MINIMAL_UBL, "test_invoice.xml")
    assert invoice.line_items == []


def test_parse_xml_unknown_format():
    """A non-UBL root element falls through to _parse_generic without raising."""
    from lib.xml_parser import parse_xml

    generic_xml = b"<SomeOtherFormat><Data>x</Data></SomeOtherFormat>"
    invoice = parse_xml(generic_xml, "generic.xml")
    # Should return a default Invoice rather than raising
    assert invoice is not None
