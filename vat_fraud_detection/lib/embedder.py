"""Thin wrapper around sentence-transformers for text embedding."""
from __future__ import annotations
from functools import lru_cache

MODEL_NAME = "all-MiniLM-L6-v2"

@lru_cache(maxsize=1)
def _get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)

def embed(texts: list[str]) -> list[list[float]]:
    """Return a list of 384-dim embedding vectors for *texts*."""
    model = _get_model()
    return model.encode(texts, show_progress_bar=False).tolist()

def embed_one(text: str) -> list[float]:
    return embed([text])[0]
