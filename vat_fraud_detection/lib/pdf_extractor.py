"""PDF invoice extraction pipeline.

Extraction strategy:
  1. pdfplumber  — extract text from each page (fast, works on text-based PDFs).
  2. pytesseract — OCR fallback if pdfplumber yields too little text
                   (scanned / image-only PDFs).
  3. LM Studio   — send the extracted text to the local LLM for structured
                   invoice field extraction (same approach as XML LLM fallback).
  4. LLM enrichment — classify each line item into a product_category.

Configure via the same environment variables as xml_extractor:
  LM_STUDIO_BASE_URL  (default: http://localhost:1234/v1)
  LM_STUDIO_MODEL     (default: mistralai/mistral-7b-instruct-v0.3)
"""
from __future__ import annotations

import io
import json
import logging
import os

from lib.models import Invoice, LineItem

log = logging.getLogger(__name__)

LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL    = os.getenv("LM_STUDIO_MODEL", "mistralai/mistral-7b-instruct-v0.3")
_LM_API_KEY        = "lm-studio"

# Minimum average characters per page below which we assume the PDF is
# image-based and fall back to OCR.
_MIN_CHARS_PER_PAGE = 50


# ── LM Studio helpers (shared schema with xml_extractor) ─────────────────────

_EXTRACTION_SYSTEM = """\
You are an invoice data extraction assistant.
Extract structured information from the invoice text and return ONLY a valid JSON object — \
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


def _lm_client():
    from openai import OpenAI
    return OpenAI(base_url=LM_STUDIO_BASE_URL, api_key=_LM_API_KEY)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


def _llm_extract(text: str, filename: str) -> Invoice:
    """Call LM Studio to extract invoice fields from plain text."""
    client = _lm_client()
    # Mistral-family templates reject "system" role — merge into user.
    merged_user = f"{_EXTRACTION_SYSTEM}\n\n-----\n{text[:12_000]}"
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


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_text_pdfplumber(pdf_bytes: bytes) -> str:
    """Extract text from all pages using pdfplumber."""
    import pdfplumber
    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n\n".join(pages)


def _extract_text_ocr(pdf_bytes: bytes) -> str:
    """Render each PDF page as an image and run Tesseract OCR on it."""
    try:
        import pytesseract
        from PIL import Image
        import pdfplumber
    except ImportError as exc:
        raise ImportError(
            "pytesseract and Pillow are required for OCR on image-based PDFs. "
            f"Original error: {exc}"
        )

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            img = page.to_image(resolution=200).original
            text = pytesseract.image_to_string(img, lang="eng")
            pages.append(text)
    return "\n\n".join(pages)


# ── Public entry point ────────────────────────────────────────────────────────

def extract_from_pdf(file_bytes: bytes, filename: str = "") -> Invoice:
    """Parse a PDF invoice and return a fully populated Invoice.

    Pipeline:
      1. Extract text with pdfplumber.
      2. If text is sparse (image-based PDF), fall back to pytesseract OCR.
      3. Send extracted text to LM Studio for structured field extraction.
      4. Enrich product_category for all line items via LM Studio.
    """
    # Step 1 — pdfplumber text extraction
    try:
        text = _extract_text_pdfplumber(file_bytes)
    except Exception as exc:
        log.warning("pdfplumber failed for %s: %s", filename, exc)
        text = ""

    # Step 2 — OCR fallback for image-based PDFs
    import pdfplumber
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        n_pages = len(pdf.pages) or 1

    avg_chars = len(text.strip()) / n_pages
    if avg_chars < _MIN_CHARS_PER_PAGE:
        log.info(
            "PDF '%s' has low text density (%.0f chars/page) — trying OCR.",
            filename, avg_chars,
        )
        try:
            text = _extract_text_ocr(file_bytes)
        except Exception as exc:
            log.warning("OCR fallback failed for %s: %s", filename, exc)

    # Step 3 — LLM extraction
    invoice = _llm_extract(text, filename)
    invoice.raw_text = text

    # Step 4 — LLM enrichment
    _llm_enrich_categories(invoice.line_items)

    return invoice
