"""
Load every data/tagged/*.json into Chroma using Voyage embeddings.

Batches Voyage calls (128 docs/batch by default) to stay well under limits.
Idempotent: Chroma upsert by id.
"""
from __future__ import annotations
import json
from pathlib import Path
from dotenv import load_dotenv
from tqdm import tqdm

from api.voyage_embed import embed
from api import chroma_store

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
TAGGED_DIR = ROOT / "data" / "tagged"
BATCH = 64


def main() -> None:
    files = sorted(TAGGED_DIR.glob("*.json"))
    if not files:
        print(f"[load_chroma] no tagged files in {TAGGED_DIR}. Run `make tag` first.")
        return

    total = 0
    for f in files:
        records: list[dict] = json.loads(f.read_text())
        if not records:
            continue
        print(f"[load_chroma] {f.name}: {len(records)} records")
        for i in tqdm(range(0, len(records), BATCH), desc=f.stem):
            chunk = records[i:i + BATCH]
            texts = [r["text"] for r in chunk]
            vecs = embed(texts, input_type="document")
            chroma_store.upsert(chunk, vecs)
            total += len(chunk)

    coll = chroma_store.get_collection()
    print(f"[load_chroma] done. upserted={total} collection_count={coll.count()}")


if __name__ == "__main__":
    main()
