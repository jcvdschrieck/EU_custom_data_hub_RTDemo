"""Walk data/legislation/, chunk, embed and upsert into ChromaDB.

Call ensure_legislation_indexed() once at app startup.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

_LEGISLATION_DIR = Path(__file__).parent.parent / "data" / "legislation"
_CHUNK_SIZE   = 500   # approximate tokens (chars / 4)
_CHUNK_OVERLAP = 50

def ensure_legislation_indexed() -> int:
    """Index any new legislation files. Returns number of new chunks added."""
    from lib import vector_store, embedder

    existing_ids = vector_store.document_ids()
    new_chunks = 0

    for file in _LEGISLATION_DIR.iterdir():
        if file.suffix.lower() not in (".pdf", ".txt"):
            continue
        text = _read_file(file)
        if not text:
            continue

        chunks = _chunk_text(text)
        ids, documents, embeddings, metadatas = [], [], [], []

        for i, chunk in enumerate(chunks):
            chunk_id = _chunk_id(file.name, i, chunk)
            if chunk_id in existing_ids:
                continue
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({"source": file.name, "chunk_index": i})

        if ids:
            embs = embedder.embed(documents)
            vector_store.upsert(ids=ids, documents=documents,
                                embeddings=embs, metadatas=metadatas)
            new_chunks += len(ids)

    return new_chunks

def _read_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            return ""
    return path.read_text(encoding="utf-8", errors="ignore")

def _chunk_text(text: str) -> list[str]:
    char_size = _CHUNK_SIZE * 4
    overlap    = _CHUNK_OVERLAP * 4
    chunks = []
    start = 0
    while start < len(text):
        end = start + char_size
        chunks.append(text[start:end])
        start += char_size - overlap
    return [c.strip() for c in chunks if c.strip()]

def _chunk_id(filename: str, index: int, content: str) -> str:
    h = hashlib.md5(f"{filename}:{index}:{content[:64]}".encode()).hexdigest()
    return h
