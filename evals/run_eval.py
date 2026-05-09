"""
Run the released CA eval CSV against the live API.

Two metrics:
  1. Citation lookup accuracy — every eval row's exact citation should resolve
  2. Factor retrieval @k — for each (factor, state), is the eval row's
     citation in the top-k semantic results filtered by factor+state?

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

    # 1) Citation lookup
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

    # 2) Factor retrieval — for each row, semantic-search by factor+state,
    # check whether the row's exact citation is in the top-K.
    hit_at_k = 0
    by_factor: dict[str, list[bool]] = defaultdict(list)
    with httpx.Client(timeout=30) as c:
        for r in rows:
            cite = r["Statute"]
            factor = r["Contributing Factor"]
            state = "CA"
            # Use the statute language as the query — proxy for "find me statutes about X"
            q = r["Statute Language"][:500]
            resp = c.get(f"{API}/search", params={
                "q": q, "state": state, "factor": factor, "k": K,
            })
            hit = False
            if resp.status_code == 200:
                cites = [h.get("citation") for h in resp.json().get("results", [])]
                hit = cite in cites
            hit_at_k += int(hit)
            by_factor[factor].append(hit)

    print(f"\n[factor retrieval @ {K}]  {hit_at_k}/{len(rows)}  ({hit_at_k / len(rows):.1%})")
    for f, hits in sorted(by_factor.items(), key=lambda x: -sum(x[1]) / max(len(x[1]), 1)):
        rate = sum(hits) / len(hits)
        print(f"  {rate:>5.1%}  ({sum(hits)}/{len(hits)})  {f}")


if __name__ == "__main__":
    main()
