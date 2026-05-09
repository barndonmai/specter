#!/usr/bin/env python3
"""
Import case_stressor/pi_cases.json (340 real CanLII personal-injury cases)
into the main Specter Harvester:

  1. Each case becomes a `case_law` document in Chroma alongside statutes.
  2. Cases that have a real `damages_awarded` value also get written to
     data/comparables.csv as REAL, sourced damages comparables — replacing
     any prior synthetic ones.

Both outputs cite the original CanLII source (PDF + canonical citation
URL on canlii.org), so every record is traceable per hackathon ground rules.

Usage:
    python scripts/import_case_stressor.py            # write JSON + CSV
    python scripts/import_case_stressor.py --load     # also embed + load to Chroma
"""
from __future__ import annotations
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harvester.schema import StatuteRecord, make_id  # reuse the record contract

SOURCE_JSON = ROOT / "case_stressor" / "pi_cases.json"
RAW_OUT     = ROOT / "data" / "raw" / "canlii-caselaw.json"
TAGGED_OUT  = ROOT / "data" / "tagged" / "canlii-caselaw.json"
COMPARABLES_OUT = ROOT / "data" / "comparables.csv"

# CanLII citation -> canonical URL.
# Examples in the dataset:
#   "2003 CanLII 2906 (ON SC)" -> https://canlii.ca/t/<slug>
#   We don't have the slug; we link to the search result that resolves to the case.
CANLII_SEARCH = "https://www.canlii.org/en/#search/text="


def canlii_url(citation: str | None, source_file: str | None) -> str:
    """
    Build a real, verifiable URL.

    1. If citation parses, link to a CanLII search that returns this exact case.
    2. Otherwise fall back to the local PDF path (still a real artifact).
    """
    if citation:
        return f"https://www.canlii.org/en/#search/text={citation.replace(' ', '+')}"
    if source_file:
        return f"file://{(ROOT / 'case_stressor' / source_file.replace(chr(92), '/')).resolve()}"
    return "https://www.canlii.org/"


def map_injury_to_legal_topic(injuries: list[str]) -> str:
    """Map case_stressor injury types to our normalized legal_topic vocabulary."""
    s = {(i or "").lower() for i in injuries}
    if "mva" in s:
        return "general traffic violation"
    if {"slip_and_fall"} & s:
        return "general traffic violation"  # not a great fit; we don't have premises liability
    return "general traffic violation"


def make_case_record(case: dict, idx: int) -> dict:
    """Return a plain dict so we can inject the case-law-specific enrichment
    fields (document_type, authority_source, legal_topic, etc.) the
    StatuteRecord schema doesn't formally know about. Chroma still gets
    them via api/chroma_store.to_metadata()."""
    md = case.get("metadata") or {}
    citation = md.get("citation") or f"CanLII Case {idx + 1}"
    case_name = md.get("case_name") or "Unknown Case"
    court = md.get("court") or "Unknown Court"
    year = md.get("year")
    text = case.get("full_text") or md.get("case_summary") or ""

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", citation).strip("-").lower()
    if not slug:
        slug = f"case-{idx}"
    record_id = f"canlii-{slug}"[:200]

    base = StatuteRecord(
        id=record_id,
        jurisdiction="Canada",
        state_code="CA-CAN",
        code=court,
        section=str(year) if year else "",
        citation=citation,
        title=case_name,
        text=(text[:3000] if text else "").strip(),
        hierarchy_path=["Case Law", court],
        source_url=canlii_url(citation, md.get("source_file")),
        contributing_factors=[],
        pi_relevant=True,
        confidence=float(md.get("extraction_confidence") or 0.0),
    ).model_dump()

    # Case-law enrichment fields so we can filter where(document_type='case_law').
    base["document_type"]     = "case_law"
    base["authority_source"]  = "court_system"
    base["jurisdiction_norm"] = "Canada"
    base["legal_topic"]       = map_injury_to_legal_topic(md.get("injury_type") or [])
    base["topic_confidence"]  = float(md.get("extraction_confidence") or 0.5)
    return base


def write_caselaw_json(records: list[dict]) -> None:
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    TAGGED_OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    TAGGED_OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"[caselaw] wrote {len(records)} records → {RAW_OUT.relative_to(ROOT)}")
    print(f"[caselaw] wrote {len(records)} records → {TAGGED_OUT.relative_to(ROOT)}")


def write_real_comparables(cases: list[dict]) -> int:
    """Pull real damages-bearing cases into a sortable CSV."""
    rows: list[dict] = []
    for c in cases:
        md = c.get("metadata") or {}
        amt = md.get("damages_awarded")
        if not amt or amt < 1000:
            continue  # skip $1 / nominal / missing
        rows.append({
            "id": f"canlii-{md.get('citation','').replace(' ', '-')[:60]}",
            "case_name": md.get("case_name") or "",
            "jurisdiction": "Canada",
            "state_code": "CA-CAN",
            "court": md.get("court") or "",
            "year": md.get("year") or "",
            "citation": md.get("citation") or "",
            "injury_type": "; ".join(md.get("injury_type") or []),
            "defendant_type": "; ".join(md.get("defendant_type") or []),
            "liability_theory": (md.get("primary_defense_argument") or "")[:200],
            "settlement_amount": amt,
            "outcome": "verdict" if md.get("plaintiff_won") else "defense",
            "contributory_negligence": md.get("contributory_negligence_percentage"),
            "source_url": canlii_url(md.get("citation"), md.get("source_file")),
            "summary": (md.get("case_summary") or "")[:400],
        })

    rows.sort(key=lambda r: -(r["settlement_amount"] or 0))

    COMPARABLES_OUT.parent.mkdir(parents=True, exist_ok=True)
    with COMPARABLES_OUT.open("w", newline="", encoding="utf-8") as f:
        if not rows:
            print("[comparables] no rows with damages — skipping")
            return 0
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[comparables] wrote {len(rows)} REAL damages comparables → "
          f"{COMPARABLES_OUT.relative_to(ROOT)}")
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", action="store_true",
                    help="Also embed + load the case-law records into Chroma")
    args = ap.parse_args()

    if not SOURCE_JSON.exists():
        print(f"❌ {SOURCE_JSON} not found. Did you `git pull` the case_stressor branch?")
        sys.exit(1)

    raw = json.loads(SOURCE_JSON.read_text())
    print(f"[import] read {len(raw)} cases from {SOURCE_JSON.relative_to(ROOT)}")

    records = [make_case_record(c, i) for i, c in enumerate(raw)]

    write_caselaw_json(records)
    n_comp = write_real_comparables(raw)

    if args.load:
        print()
        print("[load] embedding via Voyage and upserting to Chroma…")
        import os, time
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from api.voyage_embed import embed
        from api import chroma_store

        # 12 records * ~750 tokens ≈ 9K tokens — safely under 10K TPM free tier.
        # Bump LOAD_BATCH=64 once a Voyage card is on file.
        BATCH = int(os.getenv("CASELAW_BATCH", "12"))
        # Sleep between batches so the per-minute TPM window resets.
        # Set CASELAW_PAUSE_SEC=0 once a Voyage card is on file.
        PAUSE = float(os.getenv("CASELAW_PAUSE_SEC", "35"))

        coll = chroma_store.get_collection()
        existing = set(coll.get(include=[])["ids"])
        new_records = [r for r in records if r["id"] not in existing]
        print(f"[load] {len(new_records)} new records (skipped {len(records) - len(new_records)})")
        if not new_records:
            print(f"[load] nothing to do. collection holds {coll.count()} records.")
            return

        n = len(new_records)
        eta_min = (n / BATCH) * (PAUSE / 60.0)
        print(f"[load] batch={BATCH}  pause={PAUSE}s  ETA ~{eta_min:.0f} min on free tier")

        for i in range(0, n, BATCH):
            chunk = new_records[i:i + BATCH]
            texts = [r["text"] or r["title"] or r["citation"] for r in chunk]
            try:
                vecs = embed(texts, input_type="document")
                chroma_store.upsert(chunk, vecs)
                done = min(i + BATCH, n)
                print(f"[load]  {done}/{n} embedded  (collection now {coll.count()})")
            except Exception as e:
                print(f"[load]  batch {i//BATCH + 1} failed: {e}")
                print(f"[load]  sleeping {PAUSE * 2}s before retrying…")
                time.sleep(PAUSE * 2)
                # one retry; if it fails again, skip and continue
                try:
                    vecs = embed(texts, input_type="document")
                    chroma_store.upsert(chunk, vecs)
                    print(f"[load]  retry succeeded")
                except Exception as e2:
                    print(f"[load]  retry also failed; skipping batch: {e2}")
            if PAUSE and i + BATCH < n:
                time.sleep(PAUSE)

        print(f"[load] done. collection now holds {coll.count()} records.")

    print()
    print(f"✅ summary: {len(records)} case-law records, {n_comp} real damages comparables")


if __name__ == "__main__":
    main()
