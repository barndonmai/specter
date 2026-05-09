"""
PI brief formatter.

Turns a raw Harvester record (statute) into a personal-injury-lawyer-grade
brief block by joining it with hand-curated factor-level notes from
data/pi_playbook.yaml.

Design rules:
- The playbook is the FRAME (doctrine-level, hand-curated).
- The Harvester record is the CONTENT (statute-specific, retrieved).
- The formatter is pure code — no LLM call, no fabrication. Every field in
  the output traces back to either the record (statute text, citation,
  source URL) or the playbook (PI doctrine, defenses, evidence).
- Specter's commentary lines are flagged as Specter notes so a reader can
  see the difference between statutory text and editorial framing.

Used by:
  - /lookup response (api/main.py) — optional `brief` field on hit
  - pretty.py — rendered for terminal demo
  - openclaw skill pi_brief_format — rendered for WhatsApp
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_PATH = Path(os.getenv("PI_PLAYBOOK", str(ROOT / "data" / "pi_playbook.yaml")))


# ---------- playbook loading ----------

@lru_cache(maxsize=1)
def load_playbook(path: str | None = None) -> dict[str, dict[str, Any]]:
    """Load the PI playbook once, cached for the process lifetime."""
    p = Path(path) if path else PLAYBOOK_PATH
    if not p.exists():
        return {}
    with p.open("r") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def _factor_notes(factors: Iterable[str]) -> list[tuple[str, dict[str, Any]]]:
    """Return playbook entries for the record's factors, in order, deduped."""
    pb = load_playbook()
    seen: set[str] = set()
    out: list[tuple[str, dict[str, Any]]] = []
    for f in factors:
        if not f or f in seen:
            continue
        entry = pb.get(f)
        if entry:
            out.append((f, entry))
            seen.add(f)
    return out


# ---------- text helpers ----------

# Pull-quote cleanup: statute language in our seeds often has bracketed
# fragments like "[i]t is unlawful..." (a Bluebook artifact). For paste-ready
# output we strip the brackets while keeping the original case.
_BRACKET_RE = re.compile(r"\[([a-zA-Z])\]")


def clean_pull_quote(text: str, *, max_chars: int = 600) -> str:
    """De-bracket and trim a statute quote for paste-into-brief use."""
    if not text:
        return ""
    cleaned = _BRACKET_RE.sub(lambda m: m.group(1), text).strip()
    # Collapse internal whitespace runs (newlines, multi-spaces).
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 1].rstrip() + "…"
    return cleaned


def bluebook(record: dict[str, Any]) -> str:
    """
    Format a Bluebook-style citation from a record.

    Convention used here:
        Cal. Veh. Code § 23152(a) (West 2024)

    We use 'West' as the unofficial publisher conventionally cited for the
    annotated state codes; the year defaults to the current year if no
    `effective_date` field is set on the record.
    """
    cite = (record.get("citation") or "").strip()
    if not cite:
        # Fall back to code + section
        code = (record.get("code") or "").strip()
        section = (record.get("section") or "").strip()
        cite = f"{code} \u00a7 {section}".strip(" \u00a7")
    if not cite:
        return ""

    # Year: prefer effective_date, else current year as safest default.
    year = ""
    eff = record.get("effective_date")
    if isinstance(eff, str) and len(eff) >= 4 and eff[:4].isdigit():
        year = eff[:4]
    if not year:
        import datetime as _dt
        year = str(_dt.datetime.now().year)

    return f"{cite} (West {year})"


# ---------- brief assembly ----------

def build_brief(record: dict[str, Any]) -> dict[str, Any]:
    """
    Turn a Harvester record into a structured brief dict.

    Returns a dict shaped for both JSON API output and pretty-print rendering.
    Every field is either retrieved (statute / source URL) or curated
    (playbook). No LLM-generated content.
    """
    citation = (record.get("citation") or "").strip()
    section = (record.get("section") or "").strip()
    title = (record.get("title") or "").strip()
    text = record.get("text") or ""
    source_url = record.get("source_url") or ""

    def _as_list(field) -> list[str]:
        if not field:
            return []
        if isinstance(field, str):
            return [s.strip() for s in field.split(",") if s.strip()]
        return list(field)

    factors = _as_list(record.get("contributing_factors"))
    context_tags = _as_list(record.get("pi_context_tags"))

    notes = _factor_notes(factors)

    return {
        "citation": citation,
        "section": section,
        "title": title,
        "bluebook": bluebook(record),
        "pull_quote": clean_pull_quote(text),
        "source_url": source_url,
        "jurisdiction": record.get("jurisdiction") or "",
        "state_code": record.get("state_code") or "",
        "factors": factors,
        "context_tags": context_tags,
        # Per-factor notes: list of dicts so renderers can decide what to show.
        "factor_notes": [
            {
                "factor": factor,
                "nps_class_of_victim": entry.get("nps_class_of_victim", ""),
                "nps_class_of_harm": entry.get("nps_class_of_harm", ""),
                "nps_available": entry.get("nps_available"),  # true | "qualified" | "rare"
                "common_defenses": list(entry.get("common_defenses") or []),
                "evidence_to_gather": list(entry.get("evidence_to_gather") or []),
                "pi_angle": entry.get("pi_angle", ""),
            }
            for factor, entry in notes
        ],
        # Specter-flagged section so renderers can mark it visually as commentary.
        "specter_notes": _specter_notes(record, notes),
    }


def _specter_notes(record: dict[str, Any], notes: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """
    Doctrine-level commentary lines, sourced from the playbook only.
    NEVER LLM-generated. NEVER added beyond what the playbook specifies.
    """
    out: list[str] = []
    nps_calls = [(f, e.get("nps_available")) for f, e in notes]
    # Brief NPS-availability summary across all factors on the record.
    if nps_calls:
        avail = {v for _, v in nps_calls}
        if avail == {True}:
            out.append("Negligence per se available across all factors on this statute.")
        elif True in avail and ("qualified" in avail or "rare" in avail):
            out.append(
                "Negligence per se available for some factors, qualified for others — "
                "see the per-factor breakdown."
            )
        elif "qualified" in avail and "rare" not in avail:
            out.append("Negligence per se is fact-dependent; pull the evidence checklist below.")
        elif "rare" in avail and True not in avail and "qualified" not in avail:
            out.append("Negligence per se rarely sticks for this category alone — use as supporting fact.")
    # Punitive / criminal-collateral signals.
    pi_angles = " ".join(e.get("pi_angle", "") for _, e in notes).lower()
    if "punitive" in pi_angles:
        out.append("Punitive damages may be in play — check for willful/wanton conduct evidence.")
    if "collateral estoppel" in pi_angles:
        out.append("Watch for criminal conviction → collateral estoppel in civil action.")
    return out


# ---------- pretty-print renderer ----------

# ANSI helpers — match pretty.py style. Not used when rendering for the API
# (the API returns JSON dicts), but useful for terminal renderers and tests.

def _ansi(code: str) -> str:
    return f"\033[{code}m" if not _no_color() else ""


def _no_color() -> bool:
    return bool(os.getenv("NO_COLOR")) or not _stdout_is_tty()


def _stdout_is_tty() -> bool:
    try:
        import sys
        return sys.stdout.isatty()
    except Exception:
        return False


_BOLD = "1"
_DIM = "2"
_RESET = "0"
_CYAN = "36"
_GREEN = "32"
_YELLOW = "33"
_MAGENTA = "35"


def render_text(brief: dict[str, Any]) -> str:
    """Plain-text (no ANSI) renderer suitable for WhatsApp messages."""
    lines: list[str] = []
    head = brief.get("citation") or brief.get("section") or "Statute"
    if brief.get("title"):
        head = f"{head} — {brief['title']}"
    lines.append(f"🥃 {head}")
    lines.append("")

    if brief.get("bluebook"):
        lines.append("Bluebook:")
        lines.append(f"  {brief['bluebook']}")
        lines.append("")

    if brief.get("pull_quote"):
        lines.append("Pull quote (paste-ready):")
        lines.append(f"  \"{brief['pull_quote']}\"")
        lines.append("")

    for fn in brief.get("factor_notes", []):
        nps = fn.get("nps_available")
        nps_label = (
            "✅ available"
            if nps is True
            else "⚠️ qualified"
            if nps == "qualified"
            else "❌ rare"
            if nps == "rare"
            else "?"
        )
        lines.append(f"PI angle — {fn['factor']}  [NPS: {nps_label}]")
        if fn.get("nps_class_of_victim"):
            lines.append(f"  • Class of victim: {fn['nps_class_of_victim']}")
        if fn.get("nps_class_of_harm"):
            lines.append(f"  • Class of harm: {fn['nps_class_of_harm']}")
        if fn.get("pi_angle"):
            lines.append(f"  • {fn['pi_angle']}")
        if fn.get("common_defenses"):
            lines.append("  Common defenses:")
            for d in fn["common_defenses"]:
                lines.append(f"    – {d}")
        if fn.get("evidence_to_gather"):
            lines.append("  Evidence to gather:")
            for e in fn["evidence_to_gather"]:
                lines.append(f"    – {e}")
        lines.append("")

    if brief.get("context_tags"):
        lines.append("Also tagged for:")
        for t in brief["context_tags"]:
            lines.append(f"  • {t}")
        lines.append("")

    if brief.get("source_url"):
        lines.append("Source:")
        lines.append(f"  {brief['source_url']}")
        lines.append("")

    if brief.get("specter_notes"):
        lines.append("📝 My read:")
        for n in brief["specter_notes"]:
            lines.append(f"  • {n}")

    return "\n".join(lines).rstrip() + "\n"


def render_ansi(brief: dict[str, Any]) -> str:
    """Colored terminal renderer for pretty.py."""
    if _no_color():
        return render_text(brief)

    def b(c: str, t: str) -> str:
        return f"{_ansi(c)}{t}{_ansi(_RESET)}"

    lines: list[str] = []
    head = brief.get("citation") or brief.get("section") or "Statute"
    if brief.get("title"):
        head = f"{head} — {brief['title']}"
    lines.append(f"🥃 {b(_BOLD, head)}")
    lines.append("")

    if brief.get("bluebook"):
        lines.append(b(_CYAN, "Bluebook:"))
        lines.append(f"  {brief['bluebook']}")
        lines.append("")

    if brief.get("pull_quote"):
        lines.append(b(_CYAN, "Pull quote (paste-ready):"))
        lines.append(f"  \"{brief['pull_quote']}\"")
        lines.append("")

    for fn in brief.get("factor_notes", []):
        nps = fn.get("nps_available")
        nps_label = (
            b(_GREEN, "✅ available")
            if nps is True
            else b(_YELLOW, "⚠️ qualified")
            if nps == "qualified"
            else b(_DIM, "❌ rare")
            if nps == "rare"
            else "?"
        )
        lines.append(f"{b(_MAGENTA, 'PI angle')} — {fn['factor']}  [NPS: {nps_label}]")
        if fn.get("nps_class_of_victim"):
            lines.append(f"  • Class of victim: {fn['nps_class_of_victim']}")
        if fn.get("nps_class_of_harm"):
            lines.append(f"  • Class of harm: {fn['nps_class_of_harm']}")
        if fn.get("pi_angle"):
            lines.append(f"  • {fn['pi_angle']}")
        if fn.get("common_defenses"):
            lines.append(b(_CYAN, "  Common defenses:"))
            for d in fn["common_defenses"]:
                lines.append(f"    – {d}")
        if fn.get("evidence_to_gather"):
            lines.append(b(_CYAN, "  Evidence to gather:"))
            for e in fn["evidence_to_gather"]:
                lines.append(f"    – {e}")
        lines.append("")

    if brief.get("context_tags"):
        lines.append(b(_CYAN, "Also tagged for:"))
        for t in brief["context_tags"]:
            lines.append(f"  {b(_DIM, '• ' + t)}")
        lines.append("")

    if brief.get("source_url"):
        lines.append(b(_CYAN, "Source:"))
        lines.append(f"  {brief['source_url']}")
        lines.append("")

    if brief.get("specter_notes"):
        lines.append(b(_DIM, "📝 My read:"))
        for n in brief["specter_notes"]:
            lines.append(f"  {b(_DIM, '• ' + n)}")

    return "\n".join(lines).rstrip() + "\n"


# ---------- CLI ----------

if __name__ == "__main__":
    """
    Usage:
        python -m api.pi_brief                          # demo with a fake record
        python -m api.pi_brief lookup "Cal. Veh. Code § 23152(a)"   # via API
    """
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(prog="pi_brief")
    sub = ap.add_subparsers(dest="cmd")

    p_demo = sub.add_parser("demo", help="render a brief from a baked-in fake record")
    p_lookup = sub.add_parser("lookup", help="look up a citation via local API and render the brief")
    p_lookup.add_argument("citation")
    p_lookup.add_argument("--api", default=os.getenv("SPECTER_API", "http://127.0.0.1:8000"))
    p_lookup.add_argument("--json", action="store_true")

    args = ap.parse_args()

    if args.cmd in (None, "demo"):
        # A representative seed-style record so we can demo without network.
        fake = {
            "citation": "Cal. Veh. Code \u00a7 23152(a)",
            "code": "Cal. Veh. Code",
            "section": "23152(a)",
            "title": "Driving under the influence of alcohol",
            "text": "[i]t is unlawful for a person who is under the influence of any alcoholic beverage to drive a vehicle.",
            "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=VEH&sectionNum=23152.",
            "jurisdiction": "California",
            "state_code": "CA",
            "contributing_factors": ["DUI/DWI"],
        }
        brief = build_brief(fake)
        print(render_ansi(brief))
        sys.exit(0)

    if args.cmd == "lookup":
        import httpx
        try:
            r = httpx.get(f"{args.api}/lookup", params={"citation": args.citation}, timeout=15)
        except httpx.HTTPError as e:
            print(f"[pi_brief] API unreachable at {args.api}: {e}", file=sys.stderr)
            sys.exit(2)
        if r.status_code == 404:
            print(f"[pi_brief] no record for citation: {args.citation}", file=sys.stderr)
            sys.exit(1)
        if r.status_code != 200:
            print(f"[pi_brief] API error: HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
            sys.exit(2)
        record = r.json()
        brief = build_brief(record)
        if args.json:
            print(json.dumps(brief, indent=2))
        else:
            print(render_ansi(brief))
        sys.exit(0)
