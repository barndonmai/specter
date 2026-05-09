"""
Batch tag every raw statute with contributing-factor labels via Claude.

Usage:
    python -m tagger.tag data/raw                # tag all per-state JSONs
    python -m tagger.tag data/raw/ca.json        # tag a single file

Reads:  data/raw/<state>.json   (untagged StatuteRecord list)
Writes: data/tagged/<state>.json (same records, tags filled in)

Idempotent: re-tagging skips records that already have factors set,
unless --force is passed.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from tqdm import tqdm

from harvester.schema import CONTRIBUTING_FACTORS
from tagger.prompt import SYSTEM, user_prompt

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
TAGGED_DIR = ROOT / "data" / "tagged"
TAGGED_DIR.mkdir(parents=True, exist_ok=True)

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
ALLOWED = set(CONTRIBUTING_FACTORS)

client = Anthropic()


def classify_one(record: dict[str, Any]) -> dict[str, Any]:
    """Call Claude and merge the tag result back into the record."""
    try:
        msg = client.messages.create(
            model=MODEL,
            max_tokens=400,
            system=SYSTEM,
            messages=[{"role": "user", "content": user_prompt(record["citation"], record["text"])}],
        )
        raw = msg.content[0].text.strip()
        # Be forgiving if Claude wraps in fences.
        if raw.startswith("```"):
            raw = raw.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
            if raw.startswith("json"):
                raw = raw[4:].lstrip()
        data = json.loads(raw)
        factors = [f for f in data.get("factors", []) if f in ALLOWED]
        record["contributing_factors"] = factors
        record["pi_relevant"] = bool(data.get("pi_relevant", False))
        record["confidence"] = float(data.get("confidence", 0.0))
    except Exception as e:
        # Fail soft — never crash a 10k-record batch on one bad row.
        record["contributing_factors"] = record.get("contributing_factors", [])
        record["pi_relevant"] = record.get("pi_relevant")
        record["confidence"] = 0.0
        record["_tag_error"] = f"{type(e).__name__}: {e}"
    return record


def tag_file(in_path: Path, force: bool = False, workers: int = 8) -> Path:
    records: list[dict[str, Any]] = json.loads(in_path.read_text())
    out_path = TAGGED_DIR / in_path.name

    todo, done = [], []
    for r in records:
        if not force and r.get("contributing_factors"):
            done.append(r)
        else:
            todo.append(r)

    print(f"[tagger] {in_path.name}: {len(todo)} to tag, {len(done)} cached")
    results: list[dict[str, Any]] = list(done)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(classify_one, r): r for r in todo}
        for fut in tqdm(as_completed(futures), total=len(futures), desc=in_path.stem):
            results.append(fut.result())

    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"[tagger] wrote → {out_path}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(RAW_DIR),
                    help="raw JSON file or directory of files")
    ap.add_argument("--force", action="store_true", help="re-tag even cached records")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    p = Path(args.path)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    if not files:
        print(f"[tagger] no JSON files at {p}", file=sys.stderr)
        sys.exit(1)

    for f in files:
        tag_file(f, force=args.force, workers=args.workers)


if __name__ == "__main__":
    main()
