"""Placeholder tests for lib.ocr."""
from __future__ import annotations
import pytest


def test_extract_text_empty_pdf():
    """extract_text returns a string (possibly empty) for a minimal PDF stub."""
    # TODO: replace with a real minimal PDF fixture
    from lib.ocr import extract_text
    # Passing an obviously invalid byte string should return "" rather than raise
    result = extract_text(b"", "test.pdf")
    assert isinstance(result, str)


def test_extract_text_unknown_extension():
    """extract_text returns '' for unsupported file extensions."""
    from lib.ocr import extract_text
    result = extract_text(b"some data", "document.docx")
    assert result == ""


def test_extract_text_image_stub(monkeypatch):
    """extract_text delegates to _extract_image for image files."""
    from lib import ocr

    monkeypatch.setattr(ocr, "_extract_image", lambda b: "mocked ocr text")
    result = ocr.extract_text(b"fake image bytes", "scan.png")
    assert result == "mocked ocr text"
