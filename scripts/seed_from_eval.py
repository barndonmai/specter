"""
Bootstrap data/raw/<state>-eval.json from any released CSV that matches the
hackathon schema. The 17 contributing-factor categories are pre-filled as
ground-truth labels (confidence=1.0), so the tag step is a no-op for them.

Usage:
    python scripts/seed_from_eval.py                       # ALL data/eval-*-vehicle-code.csv
    python scripts/seed_from_eval.py path/to/file.csv ...  # specific files
"""
from __future__ import annotations
import csv
import json
import re
import sys
from pathlib import Path

from harvester.schema import StatuteRecord, make_id

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Map state-code → (jurisdiction name, code-slug, source URL builder)
# Add new states here as you ingest them.
STATE_PROFILES: dict[str, dict] = {
    "California": {
        "code_slug": "vc",
        "state_code": "CA",
        "url_for": lambda section: (
            "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?"
            f"lawCode=VEH&sectionNum={section.split('(')[0]}."
        ),
    },
    "Texas": {
        "code_slug": "tt",
        "state_code": "TX",
        "url_for": lambda section: (
            f"https://statutes.capitol.texas.gov/Search/Search.aspx?phrase={section.split('(')[0]}"
        ),
    },
    "Florida": {
        "code_slug": "fs",
        "state_code": "FL",
        "url_for": lambda section: (
            f"https://www.flsenate.gov/Laws/Statutes/2024/{section.split('(')[0]}"
        ),
    },
    "New York": {
        "code_slug": "vat",
        "state_code": "NY",
        "url_for": lambda section: (
            f"https://www.nysenate.gov/legislation/laws/VAT/{section.split('(')[0]}"
        ),
    },
    "Illinois": {
        "code_slug": "ilcs",
        "state_code": "IL",
        "url_for": lambda section: (
            "https://www.ilga.gov/legislation/ilcs/fulltext.asp?DocName=062500050K"
            f"{section.split('(')[0]}"
        ),
    },
    "Pennsylvania": {
        "code_slug": "75pacs",
        "state_code": "PA",
        # PA Consolidated Statutes — Title 75 (Vehicles). Public site.
        "url_for": lambda section: (
            "https://www.legis.state.pa.us/cfdocs/legis/LI/consCheck.cfm?"
            f"txtType=HTM&ttl=75&div=0&chpt=33&sctn={section.split('(')[0].split('.')[0]}"
        ),
    },
}


def out_name_for(csv_path: Path) -> str:
    """e.g. eval-tx-vehicle-code.csv -> tx-eval.json"""
    m = re.match(r"eval-([a-z]{2})-vehicle-code", csv_path.stem)
    if m:
        return f"{m.group(1)}-eval.json"
    return f"{csv_path.stem}.json"


def seed_one(csv_path: Path) -> Path:
    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        print(f"[seed] {csv_path.name}: empty, skipping")
        return csv_path

    records: list[dict] = []
    skipped: list[str] = []
    for r in rows:
        state_name = (r.get("State") or "").strip()
        profile = STATE_PROFILES.get(state_name)
        if not profile:
            skipped.append(state_name or "<blank>")
            continue

        section = (r["Section #"] or "").strip()
        text = (r.get("Statute Language") or "").strip().strip('"').strip("\u201c\u201d")
        factor = (r.get("Contributing Factor") or "").strip()

        rec = StatuteRecord(
            id=make_id(profile["state_code"], profile["code_slug"], section),
            jurisdiction=state_name,
            state_code=profile["state_code"],
            code=(r.get("Universal Citation") or "").strip(),
            section=section,
            citation=(r.get("Statute") or "").strip(),
            title=None,
            text=text,
            hierarchy_path=["Vehicle Code"],
            source_url=profile["url_for"](section),
            contributing_factors=[factor] if factor else [],
            pi_relevant=True,
            confidence=1.0,
        )
        records.append(rec.model_dump())

    # Write per-state json
    out_path = RAW_DIR / out_name_for(csv_path)
    out_path.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    print(f"[seed] {csv_path.name:>32s} -> {out_path.name:>20s}  ({len(records)} records)")
    if skipped:
        from collections import Counter
        print(f"       skipped (no state profile): {dict(Counter(skipped))}")
    return out_path


def main() -> None:
    args = sys.argv[1:]
    if args:
        paths = [Path(a) for a in args]
    else:
        paths = sorted(DATA_DIR.glob("eval-*-vehicle-code.csv"))

    if not paths:
        print("[seed] no CSVs found. Pass paths or drop CSVs into data/eval-*-vehicle-code.csv")
        sys.exit(1)

    total = 0
    for p in paths:
        if not p.exists():
            print(f"[seed] missing: {p}")
            continue
        out = seed_one(p)
        total += len(json.loads(out.read_text()))
    print(f"\n[seed] total records: {total}")


if __name__ == "__main__":
    main()
