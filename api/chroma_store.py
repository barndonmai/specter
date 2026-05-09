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

# Canada / case_stressor collection — lives in a separate Chroma persistent
# directory so we never mix US statutes with Canadian PI case law in storage.
CANADA_PERSIST_DIR = os.getenv("CANADA_PERSIST_DIR", "./case_stressor/chroma_db")
CANADA_COLLECTION_NAME = os.getenv("CANADA_COLLECTION", "pi_cases")

Path(PERSIST_DIR).mkdir(parents=True, exist_ok=True)
_client = chromadb.PersistentClient(path=PERSIST_DIR, settings=Settings(anonymized_telemetry=False))

_canada_client = None  # lazy


def _factor_flag(name: str) -> str:
    # Keep the exact category name; Chroma keys allow / and spaces.
    return f"factor_{name}"


def get_collection():
    # We bring our own embeddings (Voyage), so no embedding_function here.
    return _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def get_canada_collection():
    """Lazy-open the case_stressor/chroma_db collection (PI case law).

    Returns the chromadb Collection object directly, OR None if the
    directory or collection isn't available (graceful degrade so the
    main API keeps working even if the case_stressor branch isn't
    pulled).
    """
    global _canada_client
    p = Path(CANADA_PERSIST_DIR)
    if not p.exists():
        return None
    if _canada_client is None:
        _canada_client = chromadb.PersistentClient(
            path=str(p),
            settings=Settings(anonymized_telemetry=False),
        )
    try:
        return _canada_client.get_collection(CANADA_COLLECTION_NAME)
    except Exception:
        return None


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
    # Optional enrichment / case-law fields. None values would crash Chroma,
    # so only include keys that have a real value.
    for k in ("document_type", "authority_source", "legal_topic",
              "jurisdiction_norm", "topic_confidence"):
        v = record.get(k)
        if v is not None and v != "":
            md[k] = v
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
    legal_topic: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    document_type: Optional[str] = None,
    authority_source: Optional[str] = None,
    min_topic_confidence: Optional[float] = None,
) -> list[dict[str, Any]]:
    coll = get_collection()
    where: dict[str, Any] = {}
    if state:
        where["state_code"] = state.upper()
    if factor:
        where[_factor_flag(factor)] = True
    if pi_only:
        where["pi_relevant"] = True
    if legal_topic:
        where["legal_topic"] = legal_topic
    if jurisdiction:
        where["jurisdiction_norm"] = jurisdiction
    if document_type:
        where["document_type"] = document_type
    if authority_source:
        where["authority_source"] = authority_source
    if min_topic_confidence is not None:
        where["topic_confidence"] = {"$gte": float(min_topic_confidence)}

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


# ----------------------------------------------------------------
# Canada / case_stressor collection — separate Chroma DB, separate
# metadata schema. We translate its native fields into something the
# rest of the pipeline can render (citation, source_url, etc.).
# ----------------------------------------------------------------

def _canlii_url(citation: str | None) -> str:
    if not citation:
        return "https://www.canlii.org/"
    return f"https://www.canlii.org/en/#search/text={citation.replace(' ', '+')}"


def _canada_normalize(rec: dict[str, Any]) -> dict[str, Any]:
    """Map a case_stressor metadata row to our standard response shape."""
    return {
        "id":                rec.get("id"),
        "citation":          rec.get("citation") or "",
        "title":             rec.get("case_name") or "",
        "text":              rec.get("text") or rec.get("case_summary") or "",
        "source_url":        _canlii_url(rec.get("citation")),

        "jurisdiction":      "Canada",
        "jurisdiction_norm": "Canada",
        "state_code":        "CA-CAN",
        "code":              rec.get("court") or "",
        "section":           str(rec.get("year") or ""),
        "document_type":     "case_law",
        "authority_source":  "court_system",

        "score":             rec.get("score"),

        # PI-specific signal preserved for the Organizer
        "plaintiff_won":           rec.get("plaintiff_won"),
        "damages_awarded":         rec.get("damages_awarded"),
        "injury_type":             rec.get("injury_type"),
        "defendant_type":          rec.get("defendant_type"),
        "deciding_factor":         rec.get("deciding_factor"),
        "case_summary":            rec.get("case_summary"),
        "contributory_negligence": rec.get("contributory_negligence_found"),
        "plaintiff_age_group":     rec.get("plaintiff_age_group"),

        "pi_relevant":      True,
        "factors_csv":      "",
        "legal_topic":      "general traffic violation",
        "topic_confidence": float(rec.get("extraction_confidence") or 0.5),
    }


def canada_search(
    query_embedding: list[float],
    *,
    k: int = 10,
    min_damages: Optional[int] = None,
    plaintiff_won_only: bool = False,
    injury_substring: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Vector search over the Canada (case_stressor) collection.

    Returns [] if the Canada DB isn't available (graceful degrade).
    """
    coll = get_canada_collection()
    if coll is None:
        return []

    fetch = min(max(k * 4, 20), coll.count() or k)
    res = coll.query(
        query_embeddings=[query_embedding],
        n_results=fetch,
        include=["metadatas", "documents", "distances"],
    )
    if not res["ids"] or not res["ids"][0]:
        return []

    out: list[dict[str, Any]] = []
    for i in range(len(res["ids"][0])):
        meta = dict(res["metadatas"][0][i] or {})
        meta["id"]    = res["ids"][0][i]
        meta["text"]  = res["documents"][0][i]
        meta["score"] = 1.0 - float(res["distances"][0][i])
        norm = _canada_normalize(meta)

        if min_damages is not None:
            try:
                if (norm.get("damages_awarded") or 0) < int(min_damages):
                    continue
            except (TypeError, ValueError):
                continue
        if plaintiff_won_only and not norm.get("plaintiff_won"):
            continue
        if injury_substring:
            inj = (norm.get("injury_type") or "").lower()
            if injury_substring.lower() not in inj:
                continue

        out.append(norm)
        if len(out) >= k:
            break
    return out


def canada_count() -> int:
    coll = get_canada_collection()
    return coll.count() if coll else 0
