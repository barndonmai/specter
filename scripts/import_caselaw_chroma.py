#!/usr/bin/env python3
"""
Direct copy of case_stressor/chroma_db (340 PI cases pre-embedded with
voyage-law-2) into the main Specter collection. ZERO Voyage calls.

Reads:  case_stressor/chroma_db   (collection 'pi_cases')
Writes: ./.chroma                 (collection 'specter_statutes')

Each record gets the case-law-specific metadata fields the main pipeline
expects (document_type='case_law', authority_source='court_system',
jurisdiction_norm='Canada', source_url, citation, etc.) so it interleaves
cleanly with statute records under the same Chroma where-clause grammar.

Usage:
    python scripts/import_caselaw_chroma.py
    PYTHONPATH=. .venv/bin/python scripts/import_caselaw_chroma.py
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import chromadb
from chromadb.config import Settings

from api import chroma_store

SRC_DIR = ROOT / "case_stressor" / "chroma_db"
SRC_COLLECTION = "pi_cases"

# Same URL builder as scripts/import_case_stressor.py — point at CanLII
# search for the exact citation, fall back to local PDF.
def canlii_url(citation: str | None, source_file: str | None) -> str:
    if citation:
        return f"https://www.canlii.org/en/#search/text={citation.replace(' ', '+')}"
    if source_file:
        return f"file://{(ROOT / 'case_stressor' / source_file.replace(chr(92), '/')).resolve()}"
    return "https://www.canlii.org/"


def normalize_metadata(src_meta: dict, idx_id: str) -> tuple[str, dict]:
    """Translate case_stressor metadata → Specter metadata schema."""
    citation = src_meta.get("citation") or f"CanLII Case {idx_id}"
    case_name = src_meta.get("case_name") or "Unknown Case"
    court = src_meta.get("court") or "Unknown Court"
    year = src_meta.get("year")
    source_file = src_meta.get("source_file")

    # Derive a stable, citation-based id (matches the format used by
    # scripts/import_case_stressor.py so a future incremental load is idempotent).
    import re
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", citation).strip("-").lower() or f"case-{idx_id}"
    new_id = f"canlii-{slug}"[:200]

    md = {
        # core fields the API and pretty CLI rely on
        "jurisdiction":      "Canada",
        "jurisdiction_norm": "Canada",
        "state_code":        "CA-CAN",
        "code":              court,
        "section":           str(year) if year else "",
        "citation":          citation,
        "title":             case_name,
        "source_url":        canlii_url(citation, source_file),
        "pi_relevant":       True,
        "confidence":        float(src_meta.get("extraction_confidence") or 0.0),

        # case-law specific
        "document_type":     "case_law",
        "authority_source":  "court_system",
        "legal_topic":       "general traffic violation",  # placeholder, classifier-able later
        "topic_confidence":  float(src_meta.get("extraction_confidence") or 0.5),
        "factors_csv":       "",  # case law has no contributing-factor labels
    }

    # Preserve the case_stressor-specific signal as additional metadata.
    # (Useful for the Organizer's gap detection + comparables.)
    extras = {
        "plaintiff_won":           src_meta.get("plaintiff_won"),
        "damages_awarded":         src_meta.get("damages_awarded"),
        "injury_type":             src_meta.get("injury_type"),
        "defendant_type":          src_meta.get("defendant_type"),
        "year":                    year,
        "court_short":             court,
        "deciding_factor":         (src_meta.get("deciding_factor") or "")[:300],
        "case_summary":            (src_meta.get("case_summary") or "")[:600],
        "plaintiff_age_group":     src_meta.get("plaintiff_age_group"),
        "contributory_negligence": src_meta.get("contributory_negligence_found"),
        "credibility_issue":       src_meta.get("credibility_issue"),
        "surveillance_used":       src_meta.get("surveillance_used"),
        "expert_evidence_decisive": src_meta.get("expert_evidence_decisive"),
    }
    for k, v in extras.items():
        if v is None:
            continue
        # Chroma metadata can't store None / lists / dicts. Coerce to str | int | float | bool.
        if isinstance(v, (str, int, float, bool)):
            md[k] = v
        else:
            md[k] = str(v)

    return new_id, md


def main() -> None:
    if not SRC_DIR.exists():
        print(f"❌ {SRC_DIR} not found.")
        sys.exit(1)

    src_client = chromadb.PersistentClient(
        path=str(SRC_DIR),
        settings=Settings(anonymized_telemetry=False),
    )
    src = src_client.get_collection(SRC_COLLECTION)
    n = src.count()
    print(f"[caselaw-copy] reading {n} records from case_stressor/chroma_db/{SRC_COLLECTION}")

    # Pull EVERYTHING — embeddings, documents, metadatas — in one shot.
    res = src.get(include=["embeddings", "documents", "metadatas"])
    src_ids = res["ids"]
    embeddings = res["embeddings"]
    documents  = res["documents"]
    metadatas  = res["metadatas"] or [{}] * n

    # Confirm dim matches what we use elsewhere.
    if embeddings is not None and len(embeddings) > 0:
        dim = len(embeddings[0])
        print(f"[caselaw-copy] embedding dim = {dim} (must match voyage-law-2 = 1024)")
        if dim != 1024:
            print(f"⚠ unexpected dim {dim} — proceed with caution (cosine still works, but quality may differ)")

    # Translate ids + metadata, then upsert.
    target = chroma_store.get_collection()
    existing_ids = set(target.get(include=[])["ids"])

    new_ids: list[str] = []
    new_metas: list[dict] = []
    new_docs: list[str] = []
    new_embs: list[list[float]] = []

    skipped = 0
    for i, src_id in enumerate(src_ids):
        nid, md = normalize_metadata(metadatas[i] or {}, src_id)
        if nid in existing_ids:
            skipped += 1
            continue
        new_ids.append(nid)
        new_metas.append(md)
        new_docs.append((documents[i] or md.get("case_summary") or md.get("title") or "")[:8000])
        new_embs.append(embeddings[i].tolist() if hasattr(embeddings[i], "tolist") else list(embeddings[i]))

    if not new_ids:
        print(f"[caselaw-copy] nothing to do. target collection holds {target.count()} records.")
        return

    print(f"[caselaw-copy] upserting {len(new_ids)} new records (skipped {skipped} already present)…")
    BATCH = 200
    for i in range(0, len(new_ids), BATCH):
        target.upsert(
            ids=new_ids[i:i + BATCH],
            embeddings=new_embs[i:i + BATCH],
            documents=new_docs[i:i + BATCH],
            metadatas=new_metas[i:i + BATCH],
        )
        print(f"[caselaw-copy]  {min(i + BATCH, len(new_ids))}/{len(new_ids)} upserted")

    print(f"[caselaw-copy] done. target collection now holds {target.count()} records.")


if __name__ == "__main__":
    main()
