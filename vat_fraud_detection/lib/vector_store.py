"""ChromaDB client — initialise collection, upsert documents, query."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "data" / "chroma_db"
_COLLECTION = "vat_legislation"

@lru_cache(maxsize=1)
def _get_client():
    import chromadb
    return chromadb.PersistentClient(path=str(_DB_PATH))

def get_collection():
    client = _get_client()
    return client.get_or_create_collection(
        name=_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

def upsert(ids: list[str], documents: list[str],
           embeddings: list[list[float]], metadatas: list[dict]) -> None:
    """Add or update documents in the vector store."""
    col = get_collection()
    col.upsert(ids=ids, documents=documents,
               embeddings=embeddings, metadatas=metadatas)

def query(query_embedding: list[float], n_results: int = 5,
          where: dict | None = None) -> list[dict]:
    """Return top-n results as list of {document, metadata, distance}."""
    col = get_collection()
    kwargs: dict = dict(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )
    if where:
        kwargs["where"] = where
    results = col.query(**kwargs)
    output = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append({"document": doc, "metadata": meta, "distance": dist})
    return output

def document_ids() -> set[str]:
    """Return the set of IDs already stored (for deduplication)."""
    col = get_collection()
    return set(col.get(include=[])["ids"])
