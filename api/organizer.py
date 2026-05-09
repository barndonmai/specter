"""
Organizer — the paralegal workspace layer on top of the Harvester.

Three jobs:
  1. Tag a case description with relevant statutes (reuses /search).
  2. Surface coverage gaps (Claude reads the description, returns missing evidence).
  3. Find sortable damages comparables (filters data/comparables.csv).

This module exposes pure-python helpers; api/main.py wraps them into HTTP.
"""
from __future__ import annotations
import csv
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from anthropic import Anthropic

ROOT = Path(__file__).resolve().parents[1]
COMPARABLES_CSV = ROOT / "data" / "comparables.csv"

_anthropic_client: Anthropic | None = None


def _client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic()
    return _anthropic_client


# ---------------------------------------------------------------- COMPARABLES

@lru_cache(maxsize=1)
def load_comparables() -> list[dict[str, Any]]:
    if not COMPARABLES_CSV.exists():
        return []
    rows: list[dict[str, Any]] = []
    for r in csv.DictReader(COMPARABLES_CSV.open()):
        try:
            r["settlement_amount"] = int(r.get("settlement_amount") or 0)
        except ValueError:
            r["settlement_amount"] = 0
        try:
            r["year"] = int(r.get("year") or 0)
        except ValueError:
            r["year"] = 0
        rows.append(r)
    return rows


def search_comparables(
    *,
    state_code: Optional[str] = None,
    injury_substring: Optional[str] = None,
    defendant_type_substring: Optional[str] = None,
    min_amount: Optional[int] = None,
    max_amount: Optional[int] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    sort: str = "amount-desc",
    limit: int = 20,
) -> dict[str, Any]:
    """Filter + sort comparables. Pure local — no LLM, no Voyage."""
    rows = list(load_comparables())

    if state_code:
        rows = [r for r in rows if r.get("state_code", "").upper() == state_code.upper()]
    if injury_substring:
        q = injury_substring.lower()
        rows = [r for r in rows if q in (r.get("injury_type") or "").lower()]
    if defendant_type_substring:
        q = defendant_type_substring.lower()
        rows = [r for r in rows if q in (r.get("defendant_type") or "").lower()]
    if min_amount is not None:
        rows = [r for r in rows if r.get("settlement_amount", 0) >= min_amount]
    if max_amount is not None:
        rows = [r for r in rows if r.get("settlement_amount", 0) <= max_amount]
    if year_from is not None:
        rows = [r for r in rows if r.get("year", 0) >= year_from]
    if year_to is not None:
        rows = [r for r in rows if r.get("year", 0) <= year_to]

    if sort == "amount-desc":
        rows.sort(key=lambda r: -r.get("settlement_amount", 0))
    elif sort == "amount-asc":
        rows.sort(key=lambda r: r.get("settlement_amount", 0))
    elif sort == "year-desc":
        rows.sort(key=lambda r: -r.get("year", 0))
    elif sort == "year-asc":
        rows.sort(key=lambda r: r.get("year", 0))
    elif sort == "state":
        rows.sort(key=lambda r: (r.get("state_code", ""), -r.get("settlement_amount", 0)))

    rows = rows[:limit]

    # Stats over the (filtered) result set
    amounts = [r["settlement_amount"] for r in rows if r.get("settlement_amount", 0) > 0]
    stats = {
        "n": len(rows),
        "min":    min(amounts) if amounts else 0,
        "median": sorted(amounts)[len(amounts) // 2] if amounts else 0,
        "mean":   int(sum(amounts) / len(amounts)) if amounts else 0,
        "max":    max(amounts) if amounts else 0,
    }
    return {"stats": stats, "comparables": rows}


# ---------------------------------------------------------------- GAP DETECT

GAP_SYSTEM = """You are a paralegal triage assistant for a personal-injury firm.
You will be given a free-form case description from an attorney or paralegal.

A "complete" PI case file typically contains:
  - Police report (or CHP report)
  - Medical records (initial ER / urgent care)
  - Medical records (last 30 days)
  - Treating-physician statement
  - Photos: accident scene
  - Photos: injuries
  - Witness statements (independent)
  - Dashcam / video evidence
  - Surveillance / business-camera footage (gas stations, storefronts)
  - Insurance correspondence (UM/UIM, denials, reservation-of-rights)
  - Lost-wages documentation
  - Damages comparables (>= 5 similar cases)
  - Property damage estimates / repair invoices
  - Defendant identifying info (plate, license, employer)

Your job: for the supplied case description, identify which items the
description MENTIONS as already present, which are clearly MISSING, and
which are UNCERTAIN. Also give a 0.0-1.0 readiness_score reflecting how
prepared this file is to send a demand letter today.

Return STRICT JSON ONLY (no prose, no markdown):
{
  "have":      ["..."],
  "missing":   ["..."],
  "uncertain": ["..."],
  "readiness_score": 0.0,
  "next_actions": ["short, imperative", "..."]
}"""


def detect_gaps(case_description: str, *, model: Optional[str] = None) -> dict[str, Any]:
    """Use Claude Haiku to triage what's present / missing / uncertain."""
    model = model or os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")
    msg = _client().messages.create(
        model=model,
        max_tokens=800,
        system=GAP_SYSTEM,
        messages=[{"role": "user", "content": case_description}],
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
        if raw.startswith("json"):
            raw = raw[4:].lstrip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {
            "have": [],
            "missing": [],
            "uncertain": [],
            "readiness_score": 0.0,
            "next_actions": [],
            "_parse_error": raw[:300],
        }
