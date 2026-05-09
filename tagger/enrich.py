"""
Schema enrichment pass — adds structured metadata to every Chroma record
WITHOUT touching existing fields or embeddings.

Adds 5 new fields per record:

  1. jurisdiction_norm    : normalized state name (e.g. "California")
  2. document_type        : "statute" | "regulation" | "case_law" | "guidance" | "dataset"
  3. legal_topic          : normalized semantic legal concept (Claude)
  4. topic_confidence     : 0.0-1.0 float (Claude)
  5. authority_source     : "state_legislature" | "DMV" | "court_system" |
                            "federal_agency" | null

This is a metadata-only update — Chroma's collection.update() preserves
the existing embeddings and documents.

Usage:
    python -m tagger.enrich            # enrich every record
    python -m tagger.enrich --limit 5  # smoke test on 5 records
    python -m tagger.enrich --force    # re-enrich even records that already have legal_topic
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import chroma_store

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
client = Anthropic()


# ---------------------------------------------------------------- topics

# Normalized attorney-friendly legal-reasoning categories.
# These are deliberately broader than the raw 17 contributing-factor labels —
# they're the *semantic abstraction layer* over the factor schema.
LEGAL_TOPICS: list[str] = [
    "DUI-related behavior",
    "speeding",
    "distracted driving",
    "failure to yield",
    "reckless driving",
    "improper lane usage",
    "improper turning",
    "improper passing",
    "improper stopping or starting",
    "following too closely",
    "fleeing or evading",
    "hit and run",
    "traffic control device violation",
    "hazardous driving conditions",
    "vehicle equipment violation",
    "right-of-way violation",
    "racing or exhibition",
    "license or registration violation",
    "school zone or bus violation",
    "pedestrian or bicycle protection",
    "general traffic violation",
]

LEGAL_TOPICS_BLOCK = "\n".join(f"- {t}" for t in LEGAL_TOPICS)


SYSTEM_PROMPT = f"""You are a legal-knowledge classifier mapping U.S. motor vehicle statutes to a
normalized attorney-friendly topic taxonomy.

You will be given a single statute's citation, raw "contributing factor" label
(may be inconsistent across states), and the statute text.

Choose ONE legal_topic from this fixed list (use the EXACT string):
{LEGAL_TOPICS_BLOCK}

Rules:
1. Map similar phrases to the same canonical topic. (e.g. "DWI", "DUI",
   "Driving Under the Influence", "Intoxication Assault" -> "DUI-related behavior")
2. Prefer the most specific topic that fits.
3. If the statute genuinely fits NONE, choose "general traffic violation".
4. The label "Speeding" and "Driving Too Fast For Conditions" both map to
   "speeding".
5. "Texting While Driving", "Wireless Telephone", "Distracted Driving"
   all map to "distracted driving".
6. "Failure to Yield", "Right of Way", "Failure to Yield at Yield Sign"
   all map to "right-of-way violation" UNLESS the statute is specifically
   about yielding to pedestrians/bikes (then "pedestrian or bicycle protection").
7. confidence 0.0-1.0 — your certainty in the assignment.

Return strict JSON only — no prose, no markdown:
{{"legal_topic": "...", "topic_confidence": 0.0-1.0, "reasoning": "one short sentence"}}"""


def user_prompt(citation: str, factor: str, text: str) -> str:
    return (
        f"Citation: {citation}\n"
        f"Raw contributing factor: {factor or '(none)'}\n\n"
        f"Statute text:\n\"\"\"\n{text}\n\"\"\"\n\nClassify."
    )


# ---------------------------------------------------------------- helpers

# Normalize the existing `jurisdiction` field to canonical full state names.
JURISDICTION_NORM = {
    "California": "California",
    "Texas": "Texas",
    "Florida": "Florida",
    "Pennsylvania": "Pennsylvania",
    "New York": "New York",
    "Illinois": "Illinois",
    "CA": "California",
    "TX": "Texas",
    "FL": "Florida",
    "PA": "Pennsylvania",
    "NY": "New York",
    "IL": "Illinois",
}


def normalize_jurisdiction(meta: dict[str, Any]) -> str:
    j = (meta.get("jurisdiction") or meta.get("state_code") or "").strip()
    return JURISDICTION_NORM.get(j, j)


def infer_authority_source(meta: dict[str, Any]) -> str | None:
    """
    Heuristic guess at the issuing authority based on the `code` field.
    Conservative — returns None when uncertain so we don't fabricate.
    """
    code = (meta.get("code") or "").lower()
    if not code:
        return None
    # Vehicle / Transportation / Penal codes -> state legislature
    if any(k in code for k in ("veh. code", "vehicle code", "transp. code",
                                "transportation code", "penal code", "stat.",
                                "c.s.", "ilcs", "vat")):
        return "state_legislature"
    if "cfr" in code or "u.s.c" in code:
        return "federal_agency"
    if "dmv" in code:
        return "DMV"
    return None


def classify_one(citation: str, factor: str, text: str) -> dict[str, Any]:
    """Return {legal_topic, topic_confidence}. Fail soft on errors."""
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt(citation, factor, text)}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
        data = json.loads(raw)
        topic = data.get("legal_topic", "general traffic violation").strip()
        if topic not in LEGAL_TOPICS:
            # If Claude went off-script, snap to closest by case-insensitive match
            low = topic.lower()
            match = next((t for t in LEGAL_TOPICS if t.lower() == low), None)
            topic = match or "general traffic violation"
        return {
            "legal_topic": topic,
            "topic_confidence": float(data.get("topic_confidence", 0.5)),
        }
    except Exception as e:
        return {
            "legal_topic": "general traffic violation",
            "topic_confidence": 0.0,
            "_enrich_error": f"{type(e).__name__}: {e}",
        }


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="Only enrich the first N records (smoke test)")
    ap.add_argument("--force", action="store_true",
                    help="Re-enrich even records that already have legal_topic")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    coll = chroma_store.get_collection()
    print(f"[enrich] collection: {coll.name}, count: {coll.count()}")

    # Pull EVERY record's id + existing metadata + document text.
    # We don't include embeddings — we won't modify them.
    res = coll.get(include=["metadatas", "documents"])
    ids: list[str] = res["ids"]
    metas: list[dict[str, Any]] = res["metadatas"]
    docs: list[str] = res["documents"]

    if args.limit:
        ids, metas, docs = ids[:args.limit], metas[:args.limit], docs[:args.limit]

    todo: list[tuple[str, dict[str, Any], str]] = []
    skipped = 0
    for i, m, d in zip(ids, metas, docs):
        if not args.force and m.get("legal_topic"):
            skipped += 1
            continue
        todo.append((i, m, d))

    print(f"[enrich] {len(todo)} to enrich, {skipped} already done")
    if not todo:
        return

    # Pre-compute the deterministic fields (free) and Claude-call the rest.
    new_metas_by_id: dict[str, dict[str, Any]] = {}
    for rid, m, _ in todo:
        new_metas_by_id[rid] = {
            **m,  # preserve existing fields exactly
            "jurisdiction_norm": normalize_jurisdiction(m),
            "document_type": "statute",
            "authority_source": infer_authority_source(m),
        }

    # Threaded Claude classification.
    def worker(rid_meta_doc: tuple[str, dict[str, Any], str]) -> tuple[str, dict[str, Any]]:
        rid, m, d = rid_meta_doc
        cite = m.get("citation") or rid
        factor = m.get("factors_csv") or ""
        out = classify_one(cite, factor, d)
        return rid, out

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(worker, x) for x in todo]
        for fut in tqdm(as_completed(futures), total=len(futures), desc="enriching"):
            rid, classification = fut.result()
            new_metas_by_id[rid].update(classification)

    # Chroma can't store None values in metadata — drop them.
    cleaned_ids: list[str] = []
    cleaned_metas: list[dict[str, Any]] = []
    for rid, m in new_metas_by_id.items():
        m = {k: v for k, v in m.items() if v is not None}
        cleaned_ids.append(rid)
        cleaned_metas.append(m)

    # Update metadata only — embeddings and documents are untouched.
    BATCH = 200
    for i in range(0, len(cleaned_ids), BATCH):
        coll.update(
            ids=cleaned_ids[i:i + BATCH],
            metadatas=cleaned_metas[i:i + BATCH],
        )

    print(f"[enrich] updated {len(cleaned_ids)} records")
    # Sanity check
    sample = coll.get(ids=[cleaned_ids[0]], include=["metadatas"])
    print("[enrich] sample after update:")
    print(json.dumps(sample["metadatas"][0], indent=2, default=str))


if __name__ == "__main__":
    main()
