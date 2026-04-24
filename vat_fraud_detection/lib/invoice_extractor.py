"""Invoice extraction entry point.

Routes each uploaded file to the appropriate parser:
  - .xml  → lib.xml_extractor  (rule-based UBL/ZUGFeRD + LM Studio fallback)
  - .pdf  → lib.pdf_extractor  (pdfplumber text extraction + OCR fallback
                                 + LM Studio structured extraction)
"""
from __future__ import annotations

from lib.models import Invoice
from lib.xml_extractor import extract_from_xml
from lib.pdf_extractor import extract_from_pdf


def extract(file_bytes: bytes, filename: str = "") -> Invoice:
    """Parse an invoice file and return a populated Invoice dataclass.

    Args:
        file_bytes: Raw file content.
        filename:   Original filename (used to detect format and populate
                    Invoice.source_file).

    Returns:
        Invoice with all available fields populated and line items enriched
        with product_category classifications from LM Studio.

    Raises:
        ValueError: If the file extension is not supported.
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "xml":
        return extract_from_xml(file_bytes, filename)

    if ext == "pdf":
        return extract_from_pdf(file_bytes, filename)

    raise ValueError(
        f"Unsupported file type '.{ext}'. Only XML and PDF invoices are supported."
    )
