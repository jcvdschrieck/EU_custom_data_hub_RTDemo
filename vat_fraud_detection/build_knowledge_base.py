"""Build local VAT legislation knowledge bases.

Two collections are built from the same source text:
  - vat_legislation        : all-MiniLM-L6-v2 via sentence-transformers (384-dim)
  - vat_legislation_nomic  : nomic-embed-text-v1.5 via LM Studio (768-dim)

Steps:
  1. Parse source URLs from reference_pack_ireland_vat_sources.pdf.
  2. Fetch each source (HTML or PDF) from the web.
  3. Chunk text, preferring section/article boundaries.
     PDF sources embed page markers so each chunk carries a page range.
  4. Embed with each model and upsert into its ChromaDB collection.
  5. Run sanity-check queries against both collections.

Run once; re-runs skip already-indexed chunks (idempotent):
    python build_knowledge_base.py [--minilm-only | --nomic-only]
"""
from __future__ import annotations
import hashlib
import io
import re
import sys
import time
from pathlib import Path

ROOT       = Path(__file__).parent
PDF_PATH   = ROOT / "ireland_vat_demo_dataset" / "reference_pack_ireland_vat_sources.pdf"
CHROMA_DIR = ROOT / "data" / "chroma_db"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# ── chunking ───────────────────────────────────────────────────────────────
MIN_CHUNK = 150
MAX_CHUNK = 1_200
OVERLAP   = 150

# ── HTTP ───────────────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; VATResearchBot/1.0)"}
TIMEOUT = 30
DELAY   = 1.5

# ── URL overrides ──────────────────────────────────────────────────────────
# Correct URLs that point to index/navigation pages instead of full content.
_URL_OVERRIDES: dict[str, str] = {
    # The "front" page only lists section titles; the full act is at /revised/en/html
    "https://revisedacts.lawreform.ie/eli/2010/act/31/front/revised/en/html":
    "https://revisedacts.lawreform.ie/eli/2010/act/31/revised/en/html",
}

# ── embedder configs ───────────────────────────────────────────────────────
EMBEDDERS = {
    "minilm": {
        "collection": "vat_legislation",
        "model":      "all-MiniLM-L6-v2",
        "dims":       384,
        "description": "sentence-transformers / all-MiniLM-L6-v2 (local)",
    },
    "nomic": {
        "collection": "vat_legislation_nomic",
        "model":      "text-embedding-nomic-embed-text-v1.5",
        "dims":       768,
        "description": "nomic-embed-text-v1.5 via LM Studio (local, http://localhost:1234)",
    },
}


# ══════════════════════════════════════════════════════════════════════════
# Embedding back-ends
# ══════════════════════════════════════════════════════════════════════════

def embed_minilm(texts: list[str], model_name: str) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)
    return model.encode(texts, show_progress_bar=False).tolist()


def embed_nomic(texts: list[str], model_name: str) -> list[list[float]]:
    from openai import OpenAI
    client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")
    results: list[list[float]] = []
    batch_size = 64
    for start in range(0, len(texts), batch_size):
        batch = texts[start:start + batch_size]
        resp = client.embeddings.create(model=model_name, input=batch)
        results.extend([d.embedding for d in resp.data])
    return results


def get_embed_fn(key: str):
    if key == "minilm":
        return embed_minilm
    if key == "nomic":
        return embed_nomic
    raise ValueError(f"Unknown embedder key: {key}")


# ══════════════════════════════════════════════════════════════════════════
# ChromaDB helpers
# ══════════════════════════════════════════════════════════════════════════

def get_collection(name: str):
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_batch(collection, ids, docs, embeddings, metas, batch=100) -> None:
    for start in range(0, len(ids), batch):
        collection.upsert(
            ids=ids[start:start + batch],
            documents=docs[start:start + batch],
            embeddings=embeddings[start:start + batch],
            metadatas=metas[start:start + batch],
        )


# ══════════════════════════════════════════════════════════════════════════
# Source fetching
# ══════════════════════════════════════════════════════════════════════════

_URL_RE = re.compile(r'https?://\S+')

# Page markers embedded in PDF text so chunker preserves page provenance
_PAGE_MARKER_RE = re.compile(r'<<<PAGE:(\d+)>>>')


def parse_sources(pdf_path: Path) -> list[dict]:
    import pdfplumber
    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            lines.extend((page.extract_text() or "").splitlines())

    sources: list[dict] = []
    pending_label = ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("Tip:"):
            continue
        url_match = _URL_RE.search(line)
        if url_match:
            url = url_match.group(0).rstrip(".")
            url = _URL_OVERRIDES.get(url, url)
            sources.append({"label": pending_label or url, "url": url})
            pending_label = ""
        else:
            pending_label = (pending_label + " " + line).strip() if pending_label else line
    return sources


def fetch(url: str) -> tuple[str, str]:
    import requests
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "pdf" in ct or url.lower().endswith(".pdf"):
            return "pdf", _pdf_from_bytes(resp.content)
        return "html", _html_to_text(resp.text)
    except Exception as e:
        print(f"      ! fetch failed: {e}")
        return "", ""


def _pdf_from_bytes(content: bytes) -> str:
    """Extract PDF text with <<<PAGE:N>>> markers between pages.

    Markers survive the chunker so each chunk can be mapped back to the
    page(s) it came from.
    """
    import pdfplumber
    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                t = page.extract_text() or ""
                if t.strip():
                    parts.append(f"<<<PAGE:{i}>>>")
                    parts.append(t)
    except Exception as e:
        print(f"      ! PDF parse error: {e}")
    return "\n".join(parts)


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "aside", "form", "noscript"]):
        tag.decompose()
    lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# Chunking — page-aware
# ══════════════════════════════════════════════════════════════════════════

_SECTION_RE = re.compile(
    r"(?m)^(?:"
    r"(?:Section|Article|Chapter|Part|Schedule)\s+\d+"
    r"|(?:\d+\.)+\s+[A-Z]"
    r"|[A-Z][A-Z\s]{10,}$"
    r")"
)


def _raw_chunks(text: str) -> list[str]:
    """Split text into raw chunks (may still contain page markers)."""
    if not text.strip():
        return []
    sections = _SECTION_RE.split(text)
    headings = _SECTION_RE.findall(text)
    labelled = ([("", sections[0])] if sections[0].strip() else [])
    if headings:
        labelled += list(zip(headings, sections[1:]))
    else:
        labelled = labelled or [("", text)]

    chunks: list[str] = []
    for heading, body in labelled:
        block = (f"{heading}\n{body}").strip() if heading else body.strip()
        if not block:
            continue
        if len(block) <= MAX_CHUNK:
            if len(block) >= MIN_CHUNK:
                chunks.append(block)
        else:
            start = 0
            while start < len(block):
                piece = block[start:start + MAX_CHUNK].strip()
                if len(piece) >= MIN_CHUNK:
                    chunks.append(piece)
                start += MAX_CHUNK - OVERLAP
    return chunks


def chunk_text(text: str) -> list[dict]:
    """Return chunks as dicts with keys: text, page_start, page_end.

    page_start / page_end are None for HTML sources (no page concept).
    """
    result = []
    for raw in _raw_chunks(text):
        page_nums = [int(m) for m in _PAGE_MARKER_RE.findall(raw)]
        clean = _PAGE_MARKER_RE.sub("", raw).strip()
        if not clean:
            continue
        result.append({
            "text":       clean,
            "page_start": min(page_nums) if page_nums else None,
            "page_end":   max(page_nums) if page_nums else None,
        })
    return result


def chunk_id(source_url: str, index: int, text: str) -> str:
    return hashlib.md5(f"{source_url}:{index}:{text[:64]}".encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# Sanity-check queries
# ══════════════════════════════════════════════════════════════════════════

_QUERIES = [
    "standard VAT rate Ireland",
    "food and beverages reduced rate",
    "zero rated goods",
    "electronic publications e-books",
]


def verify(collection, embed_fn, model_name: str) -> None:
    print("  Sanity-check queries:")
    for q in _QUERIES:
        vec = embed_fn([q], model_name)
        res = collection.query(
            query_embeddings=vec, n_results=1,
            include=["documents", "metadatas", "distances"],
        )
        doc  = res["documents"][0][0][:90].replace("\n", " ")
        dist = res["distances"][0][0]
        meta = res["metadatas"][0][0]
        src  = meta.get("source_label", "")[:30]
        pg   = meta.get("page_start")
        pg_s = f" p.{pg}" if pg else ""
        print(f"    Q: {q}")
        print(f"       dist={dist:.3f}  [{src}{pg_s}]  \"{doc}...\"")


# ══════════════════════════════════════════════════════════════════════════
# Stale-chunk cleanup
# ══════════════════════════════════════════════════════════════════════════

def cleanup_replaced_urls(keys: list[str]) -> None:
    """Delete any chunks that were indexed under a now-overridden URL."""
    if not _URL_OVERRIDES:
        return
    for key in keys:
        cfg = EMBEDDERS[key]
        col = get_collection(cfg["collection"])
        for old_url in _URL_OVERRIDES:
            res = col.get(where={"source_url": {"$eq": old_url}}, include=[])
            if res["ids"]:
                print(f"  Removing {len(res['ids'])} stale chunks from {old_url[:70]}")
                col.delete(ids=res["ids"])


# ══════════════════════════════════════════════════════════════════════════
# Core indexing logic for one collection
# ══════════════════════════════════════════════════════════════════════════

def index_collection(key: str, chunks_by_source: list[dict]) -> None:
    cfg        = EMBEDDERS[key]
    embed_fn   = get_embed_fn(key)
    collection = get_collection(cfg["collection"])
    existing   = set(collection.get(include=[])["ids"])

    print(f"\n  Collection : {cfg['collection']}")
    print(f"  Model      : {cfg['description']}")
    print(f"  Existing   : {len(existing)} chunks")

    total_new = 0
    for source in chunks_by_source:
        url    = source["url"]
        label  = source["label"]
        chunks = source["chunks"]   # list[dict] with text, page_start, page_end

        new_ids, new_docs, new_metas = [], [], []
        for i, chunk in enumerate(chunks):
            text = chunk["text"]
            cid  = chunk_id(url, i, text)
            if cid in existing:
                continue
            new_ids.append(cid)
            new_docs.append(text)
            # First non-empty line is typically a section/article heading
            section_heading = next(
                (l.strip() for l in text.splitlines() if l.strip()), ""
            )[:120]
            meta: dict = {
                "source_label":    label,
                "source_url":      url,
                "chunk":           i,
                "country":         "IE",
                "section_heading": section_heading,
            }
            if chunk["page_start"] is not None:
                meta["page_start"] = chunk["page_start"]
            if chunk["page_end"] is not None:
                meta["page_end"] = chunk["page_end"]
            new_metas.append(meta)

        if not new_ids:
            continue

        print(f"  + {len(new_ids):3d} chunks  <- {label[:50]}")
        embeddings = embed_fn(new_docs, cfg["model"])
        upsert_batch(collection, new_ids, new_docs, embeddings, new_metas)
        existing.update(new_ids)
        total_new += len(new_ids)

    total = collection.count()
    print(f"  Added {total_new} new.  Total: {total} chunks.")

    if total > 0:
        verify(collection, embed_fn, cfg["model"])


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def build(keys: list[str]) -> None:
    print(f"\n{'='*62}")
    print("  VAT Knowledge Base Builder — Ireland")
    print(f"{'='*62}")

    print(f"\n{'='*62}")
    print("  Cleaning up stale chunks from overridden URLs")
    print(f"{'='*62}")
    cleanup_replaced_urls(keys)

    sources = parse_sources(PDF_PATH)
    print(f"\nFound {len(sources)} source(s). Fetching content...\n")

    chunks_by_source: list[dict] = []
    for s in sources:
        print(f"  {s['url']}")
        ctype, text = fetch(s["url"])
        if not text:
            print("    -> skipped (no content)")
            continue
        chunks = chunk_text(text)
        pages  = [c["page_start"] for c in chunks if c["page_start"] is not None]
        pg_info = f", pages {min(pages)}–{max(pages)}" if pages else ""
        print(f"    -> {len(text):,} chars ({ctype}), {len(chunks)} chunks{pg_info}")
        if chunks:
            chunks_by_source.append({
                "url":    s["url"],
                "label":  s["label"],
                "chunks": chunks,
            })
        time.sleep(DELAY)

    total_chunks = sum(len(s["chunks"]) for s in chunks_by_source)
    print(f"\n{total_chunks} chunks from {len(chunks_by_source)} source(s)")

    print(f"\n{'='*62}")
    print("  Indexing collections")
    print(f"{'='*62}")

    for key in keys:
        index_collection(key, chunks_by_source)

    print(f"\n{'='*62}")
    print(f"  Done.  Store: {CHROMA_DIR}")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    if not PDF_PATH.exists():
        print(f"ERROR: {PDF_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    args = sys.argv[1:]
    if "--minilm-only" in args:
        keys = ["minilm"]
    elif "--nomic-only" in args:
        keys = ["nomic"]
    else:
        keys = ["minilm", "nomic"]

    build(keys)
