"""
Run the released CA eval CSV against the live API.

Two metrics:
  1. Citation lookup accuracy — every eval row's exact citation should resolve
  2. Factor retrieval @k — for each (factor, state), is the eval row's
     citation in the top-k semantic results filtered by factor+state?

Voyage rate-limiting is centralized in api/voyage_embed.py (VOYAGE_RPM env).
This script does not throttle on its own — the embed layer takes care of it,
including caching repeated queries and retrying on 429.

Usage:
    make serve   # in another terminal
    make eval
"""
from __future__ import annotations
import csv
import os
from collections import defaultdict
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "eval-ca-vehicle-code.csv"
API = os.getenv("SPECTER_API", "http://127.0.0.1:8000")
K = 10


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open()))
    print(f"[eval] loaded {len(rows)} eval rows from {CSV_PATH.name}")
    print(f"[eval] API: {API}")
    print(f"[eval] Voyage rate-limiting is enforced inside the API "
          f"(see VOYAGE_RPM in .env)")

    # 1) Citation lookup — pure Chroma metadata lookup, no embeddings.
    found = 0
    missing: list[str] = []
    with httpx.Client(timeout=30) as c:
        for r in rows:
            cite = r["Statute"]
            resp = c.get(f"{API}/lookup", params={"citation": cite})
            if resp.status_code == 200:
                found += 1
            else:
                missing.append(cite)
    print(f"\n[citation lookup]  {found}/{len(rows)} found  ({found / len(rows):.1%})")
    for m in missing[:10]:
        print(f"  MISS  {m}")

    # 2) Factor retrieval — semantic search per row.
    hit_at_k = 0
    by_factor: dict[str, list[bool]] = defaultdict(list)
    errors = 0
    with httpx.Client(timeout=120) as c:
        for i, r in enumerate(rows):
            cite = r["Statute"]
            factor = r["Contributing Factor"]
            state = "CA"
            q = r["Statute Language"][:500]

            try:
                resp = c.get(f"{API}/search", params={
                    "q": q, "state": state, "factor": factor, "k": K,
                })
            except Exception as e:
                print(f"  [err] {cite}: {e}")
                errors += 1
                by_factor[factor].append(False)
                continue

            hit = False
            if resp.status_code == 200:
                cites = [h.get("citation") for h in resp.json().get("results", [])]
                hit = cite in cites
            else:
                errors += 1
                if i < 3:
                    print(f"  [warn] {resp.status_code} for {cite!r}: {resp.text[:120]}")

            hit_at_k += int(hit)
            by_factor[factor].append(hit)
            print(f"  [{i+1:>2d}/{len(rows)}] {factor:<40s} {cite}  -> {'HIT' if hit else 'miss'}")

    print(f"\n[factor retrieval @ {K}]  {hit_at_k}/{len(rows)}  ({hit_at_k / len(rows):.1%})")
    if errors:
        print(f"  ⚠ {errors} request(s) errored. If 429s, bump VOYAGE_RPM in .env after adding a Voyage card.")
    for f, hits in sorted(by_factor.items(), key=lambda x: -sum(x[1]) / max(len(x[1]), 1)):
        rate = sum(hits) / len(hits) if hits else 0
        print(f"  {rate:>5.1%}  ({sum(hits)}/{len(hits)})  {f}")


if __name__ == "__main__":
    main()
