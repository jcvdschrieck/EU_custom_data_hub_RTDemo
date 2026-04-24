"""Retrieve relevant legislation chunks for a given invoice line item."""
from __future__ import annotations

from lib.models import LineItem
from lib import embedder, vector_store


def retrieve(line_item: LineItem, n_results: int = 6) -> list[dict]:
    """Return the top-n legislation chunks most relevant to *line_item*.

    The query combines description, VAT rate, and product category so the
    vector search targets both the item type and the applicable rate rule.
    """
    query_text = " ".join(filter(None, [
        line_item.description,
        f"VAT rate {line_item.vat_rate_applied:.0%}",
        line_item.product_category,
    ]))
    query_vec = embedder.embed_one(query_text)
    return vector_store.query(query_vec, n_results=n_results)


def deduplicate(chunks: list[dict]) -> list[dict]:
    """Remove duplicate documents, preserving the highest-relevance copy."""
    seen: set[str] = set()
    result = []
    for chunk in chunks:
        doc = chunk["document"]
        if doc not in seen:
            seen.add(doc)
            result.append(chunk)
    return result


def format_context(chunks: list[dict]) -> str:
    """Format retrieved chunks as a numbered context block for the LLM prompt.

    Each entry includes the source label, URL, and the opening line of the chunk
    (which is typically a section heading) so the LLM can produce precise
    legislation references.
    """
    entries = []
    for i, chunk in enumerate(chunks, 1):
        meta  = chunk["metadata"]
        label = meta.get("source_label") or meta.get("source") or "Unknown source"
        url   = meta.get("source_url", "")

        # Prefer stored section_heading metadata; fall back to first chunk line
        section = meta.get("section_heading") or next(
            (l.strip() for l in chunk["document"].splitlines() if l.strip()),
            "",
        )
        if len(section) > 100:
            section = section[:100] + "…"

        page_start = meta.get("page_start")
        page_end   = meta.get("page_end")
        if page_start and page_end and page_start != page_end:
            page_info = f"pp. {page_start}–{page_end}"
        elif page_start:
            page_info = f"p. {page_start}"
        else:
            page_info = ""

        header = f"[{i}] {label}"
        if url:
            header += f"\n    URL: {url}"
        if section:
            header += f"\n    Section: {section}"
        if page_info:
            header += f"\n    Pages: {page_info}"

        entries.append(f"{header}\n{chunk['document']}")
    return "\n\n".join(entries)
