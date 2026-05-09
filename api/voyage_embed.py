"""
Voyage embeddings — `voyage-law-2` is trained for legal text. Use that.
"""
from __future__ import annotations
import os
from typing import Sequence
import voyageai

_MODEL = os.getenv("VOYAGE_MODEL", "voyage-law-2")
_client = voyageai.Client()  # picks up VOYAGE_API_KEY from env


def embed(texts: Sequence[str], input_type: str = "document") -> list[list[float]]:
    """input_type: 'document' for indexing, 'query' for search-time."""
    if not texts:
        return []
    res = _client.embed(list(texts), model=_MODEL, input_type=input_type)
    return res.embeddings
