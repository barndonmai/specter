"""
Load every data/tagged/*.json into Chroma using Voyage embeddings.

Batches Voyage calls (128 docs/batch by default) to stay well under limits.
Idempotent: Chroma upsert by id.
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

from api.voyage_embed import embed
from api import chroma_store

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
TAGGED_DIR = ROOT / "data" / "tagged"

# Voyage free tier: 10K tokens / minute. A typical statute is ~150 tokens,
# so a batch of 32 is ~5K tokens — safely under TPM. Bump to 64 once you've
# added a Voyage payment method (TPM jumps to 1M+).
BATCH = int(os.getenv("LOAD_BATCH", "32"))


def main() -> None:
    files = sorted(TAGGED_DIR.glob("*.json"))
    if not files:
        print(f"[load_chroma] no tagged files in {TAGGED_DIR}. Run `make tag` first.")
        return

    # Find which IDs are already in Chroma so we can skip re-embedding them.
    # Pass FORCE_RELOAD=1 to ignore the cache and re-embed everything.
    force = os.getenv("FORCE_RELOAD", "").lower() in ("1", "true", "yes")
    coll = chroma_store.get_collection()
    existing_ids: set[str] = set()
    if not force:
        try:
            existing_ids = set(coll.get(include=[])["ids"])
            print(f"[load_chroma] {len(existing_ids)} records already in Chroma — skipping those")
            print("[load_chroma]   (set FORCE_RELOAD=1 to re-embed everything)")
        except Exception as e:
            print(f"[load_chroma] couldn't read existing ids ({e}); loading everything")

    total = 0
    skipped = 0
    for f in files:
        records: list[dict] = json.loads(f.read_text())
        if not records:
            continue

        # Drop records that are already loaded.
        new_records = [r for r in records if r["id"] not in existing_ids]
        skipped_here = len(records) - len(new_records)
        skipped += skipped_here

        if not new_records:
            print(f"[load_chroma] {f.name}: {len(records)} records, all already loaded — skip")
            continue

        print(f"[load_chroma] {f.name}: {len(new_records)} new records "
              f"({skipped_here} cached) — embedding")
        for i in tqdm(range(0, len(new_records), BATCH), desc=f.stem):
            chunk = new_records[i:i + BATCH]
            texts = [r["text"] for r in chunk]
            vecs = embed(texts, input_type="document")
            chroma_store.upsert(chunk, vecs)
            total += len(chunk)
            # Free tier TPM safety: ~5K tokens per batch of 32 + 25s sleep
            # = ~12K TPM ceiling, well under the 10K window threshold.
            # Set LOAD_TPM_PAUSE_SEC=0 after adding a Voyage payment method.
            pause = float(os.getenv("LOAD_TPM_PAUSE_SEC", "25"))
            if pause > 0 and i + BATCH < len(new_records):
                time.sleep(pause)

    if skipped:
        print(f"[load_chroma] skipped {skipped} already-loaded records (saved Voyage calls)")

    coll = chroma_store.get_collection()
    print(f"[load_chroma] done. upserted={total} collection_count={coll.count()}")


if __name__ == "__main__":
    main()
