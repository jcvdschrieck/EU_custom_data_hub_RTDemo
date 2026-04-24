"""Extract text from PDF and image invoices.

Strategy:
  1. pdfplumber for digitally-created PDFs (fast, no vision needed).
  2. pytesseract fallback for scanned pages / image files.
"""
from __future__ import annotations
import io
from pathlib import Path

def extract_text(file_bytes: bytes, filename: str) -> str:
    """Return plain text extracted from *file_bytes*.

    Args:
        file_bytes: Raw file content.
        filename:   Original filename (used to detect format).

    Returns:
        Extracted text string, may be empty if extraction fails.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(file_bytes)
    elif suffix in (".jpg", ".jpeg", ".png", ".tiff", ".bmp"):
        return _extract_image(file_bytes)
    else:
        return ""

def _extract_pdf(file_bytes: bytes) -> str:
    import pdfplumber
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if len(page_text.strip()) < 50:
                # Likely scanned — fall back to OCR on page image
                page_text = _ocr_page_image(page)
            text_parts.append(page_text)
    return "\n".join(text_parts)

def _extract_image(file_bytes: bytes) -> str:
    from PIL import Image
    import pytesseract
    image = Image.open(io.BytesIO(file_bytes))
    return pytesseract.image_to_string(image)

def _ocr_page_image(page) -> str:  # pdfplumber Page
    try:
        from PIL import Image
        import pytesseract
        img = page.to_image(resolution=200).original
        return pytesseract.image_to_string(img)
    except Exception:
        return ""
