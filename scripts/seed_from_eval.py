"""
Bootstrap data/raw/ca-eval.json from the released CSV so the rest of the
pipeline (tag → load → serve → eval) can run end-to-end *immediately*
while real scrapers are still being built.

The 41 CA rows here also already carry a labeled `Contributing Factor`,
so we pre-fill that. The tagger will then validate / extend it.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path

from harvester.schema import StatuteRecord, make_id

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "eval-ca-vehicle-code.csv"
OUT = ROOT / "data" / "raw" / "ca-eval.json"


def slug_for_section(section: str) -> str:
    return section


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open()))
    records: list[dict] = []
    for r in rows:
        section = r["Section #"].strip()
        rec = StatuteRecord(
            id=make_id("CA", "vc", section),
            jurisdiction="California",
            state_code="CA",
            code=r["Universal Citation"].strip(),
            section=section,
            citation=r["Statute"].strip(),
            title=None,
            text=r["Statute Language"].strip().strip('"').strip("\u201c\u201d"),
            hierarchy_path=["Vehicle Code"],
            source_url=(
                "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?"
                f"lawCode=VEH&sectionNum={section.split('(')[0]}."
            ),
            contributing_factors=[r["Contributing Factor"].strip()] if r.get("Contributing Factor") else [],
            pi_relevant=True,
            confidence=1.0,  # ground-truth label
        )
        records.append(rec.model_dump())

    OUT.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"[seed] wrote {len(records)} records → {OUT}")


if __name__ == "__main__":
    main()
