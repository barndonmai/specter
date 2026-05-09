#!/usr/bin/env python3
"""
TPM-safe loader for the case-law records from data/tagged/canlii-caselaw.json.

Reads texts already capped at 3K chars by import_case_stressor.py, embeds in
small batches (8 docs ≈ 6K tokens), pauses 25s between batches, and flushes
output so you can watch it work.

Usage:
    python scripts/load_caselaw.py
    PYTHONPATH=. .venv/bin/python scripts/load_caselaw.py
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from api.voyage_embed import embed
from api import chroma_store

PATH = ROOT / "data" / "tagged" / "canlii-caselaw.json"
# Voyage free-tier TPM = 10K/min. Each text ~= 750 tokens at 3000 chars,
# but the rate-limiter + cache layer adds overhead. Tighten both.
BATCH = int(os.getenv("CASELAW_BATCH", "4"))
PAUSE = float(os.getenv("CASELAW_PAUSE_SEC", "30"))
# Hard cap on text length per record before embedding. ~1500 chars ≈ 380 tokens.
# 4 records * 380 tokens = ~1.5K TPM. Comfortably under cap.
MAX_CHARS = int(os.getenv("CASELAW_MAX_CHARS", "1500"))


def log(msg: str) -> None:
    print(msg, flush=True)


def main() -> None:
    if not PATH.exists():
        log(f"❌ {PATH} not found. Run scripts/import_case_stressor.py first.")
        sys.exit(1)

    records: list[dict] = json.loads(PATH.read_text())
    log(f"[caselaw-load] read {len(records)} records from {PATH.relative_to(ROOT)}")

    coll = chroma_store.get_collection()
    existing = set(coll.get(include=[])["ids"])
    new = [r for r in records if r["id"] not in existing]
    log(f"[caselaw-load] {len(new)} new (skipping {len(records) - len(new)} cached)")
    if not new:
        log(f"[caselaw-load] nothing to do. collection holds {coll.count()} records.")
        return

    eta_min = (len(new) / BATCH) * (PAUSE / 60.0)
    log(f"[caselaw-load] batch={BATCH} pause={PAUSE}s  ETA ~{eta_min:.1f} min on free tier")
    log(f"[caselaw-load] (set CASELAW_PAUSE_SEC=0 once a Voyage card is on file)")
    log("")

    n = len(new)
    failed_ids: list[str] = []
    for i in range(0, n, BATCH):
        chunk = new[i:i + BATCH]
        texts = [(r.get("text") or r.get("title") or r.get("citation") or "")[:MAX_CHARS]
                 for r in chunk]
        try:
            t0 = time.time()
            vecs = embed(texts, input_type="document")
            chroma_store.upsert(chunk, vecs)
            elapsed = time.time() - t0
            done = min(i + BATCH, n)
            log(f"[caselaw-load]  {done:>3d}/{n}  embedded in {elapsed:.1f}s "
                f"— collection={coll.count()}")
        except Exception as e:
            log(f"[caselaw-load]  batch starting at {i}: FAILED — {type(e).__name__}: {str(e)[:100]}")
            failed_ids.extend(r["id"] for r in chunk)

        if PAUSE and i + BATCH < n:
            log(f"[caselaw-load]  sleeping {PAUSE}s for TPM window…")
            time.sleep(PAUSE)

    log("")
    log(f"[caselaw-load] DONE. collection={coll.count()}  failed={len(failed_ids)}")
    if failed_ids:
        log(f"[caselaw-load] re-run to retry the {len(failed_ids)} failed records.")


if __name__ == "__main__":
    main()
