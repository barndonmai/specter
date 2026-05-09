"""
Thin Chroma wrapper. Persistent local store.

NOTE on Chroma + array fields:
Chroma's `where` clause does not support array-contains. We work around it
by storing `factor_<NAME>: True` boolean flags on each record's metadata,
plus a comma-joined `factors_csv` for human display. This lets callers
filter "give me everything tagged DUI/DWI" with `where={"factor_DUI/DWI": True}`.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Optional
import chromadb
from chromadb.config import Settings

PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./.chroma")
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION", "specter_statutes")

Path(PERSIST_DIR).mkdir(parents=True, exist_ok=True)
_client = chromadb.PersistentClient(path=PERSIST_DIR, settings=Settings(anonymized_telemetry=False))


def _factor_flag(name: str) -> str:
    # Keep the exact category name; Chroma keys allow / and spaces.
    return f"factor_{name}"


def get_collection():
    # We bring our own embeddings (Voyage), so no embedding_function here.
    return _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def to_metadata(record: dict[str, Any]) -> dict[str, Any]:
    md: dict[str, Any] = {
        "jurisdiction": record["jurisdiction"],
        "state_code": record["state_code"],
        "code": record["code"],
        "section": record["section"],
        "citation": record["citation"],
        "title": record.get("title") or "",
        "source_url": record["source_url"],
        "pi_relevant": bool(record.get("pi_relevant") or False),
        "confidence": float(record.get("confidence") or 0.0),
        "factors_csv": ",".join(record.get("contributing_factors") or []),
        "context_tags_csv": ",".join(record.get("pi_context_tags") or []),
    }
    for f in record.get("contributing_factors") or []:
        md[_factor_flag(f)] = True
    # Mirror the per-tag flag pattern for context tags so callers can filter
    # `where={"context_Bicycle Violation": True}` exactly like factors.
    for t in record.get("pi_context_tags") or []:
        md[f"context_{t}"] = True
    return md


def upsert(records: list[dict[str, Any]], embeddings: list[list[float]]) -> None:
    if not records:
        return
    coll = get_collection()
    coll.upsert(
        ids=[r["id"] for r in records],
        documents=[r["text"] for r in records],
        embeddings=embeddings,
        metadatas=[to_metadata(r) for r in records],
    )


def lookup_by_citation(citation: str) -> Optional[dict[str, Any]]:
    coll = get_collection()
    res = coll.get(where={"citation": citation}, limit=1)
    if not res["ids"]:
        return None
    return _row(res, 0)


def search(
    query_embedding: list[float],
    state: Optional[str] = None,
    factor: Optional[str] = None,
    pi_only: bool = False,
    k: int = 10,
) -> list[dict[str, Any]]:
    coll = get_collection()
    where: dict[str, Any] = {}
    if state:
        where["state_code"] = state.upper()
    if factor:
        where[_factor_flag(factor)] = True
    if pi_only:
        where["pi_relevant"] = True

    # Chroma wants $and when there are multiple keys
    if len(where) > 1:
        where = {"$and": [{k: v} for k, v in where.items()]}
    elif not where:
        where = None  # type: ignore[assignment]

    res = coll.query(
        query_embeddings=[query_embedding],
        n_results=k,
        where=where,
    )
    out: list[dict[str, Any]] = []
    if not res["ids"] or not res["ids"][0]:
        return out
    for i in range(len(res["ids"][0])):
        out.append({
            "id": res["ids"][0][i],
            "score": 1.0 - float(res["distances"][0][i]),  # cosine sim
            "text": res["documents"][0][i],
            **res["metadatas"][0][i],
        })
    return out


def _row(res: dict[str, Any], i: int) -> dict[str, Any]:
    out = {
        "id": res["ids"][i],
        "text": res["documents"][i],
        **(res["metadatas"][i] or {}),
    }
    # Reconstruct list-shaped fields from their CSV mirrors so callers don't
    # have to re-implement the unflatten. Chroma stores arrays as a CSV string
    # + per-value boolean flags; the canonical list is what consumers want.
    if "contributing_factors" not in out:
        csv = out.get("factors_csv") or ""
        out["contributing_factors"] = [f.strip() for f in csv.split(",") if f.strip()]
    if "pi_context_tags" not in out:
        csv = out.get("context_tags_csv") or ""
        out["pi_context_tags"] = [t.strip() for t in csv.split(",") if t.strip()]
    return out
