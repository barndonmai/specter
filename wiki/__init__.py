"""
Authoritative-source wiki loader.

Two layers:
  1. `sources.yaml`        — the catalog (22 sources, what each is)
  2. `authority_map.yaml`  — the routing (which source for which need)

The hackathon brief asks for "a curated wiki of which online sources are
authoritative for what." Together these two files answer that.

Usage:
    from wiki import (
        load_sources, load_authority_map,
        get, find_for_state, find_by_kind,
        route_for_need, route_for_topic,
    )
"""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional
import yaml

_DIR = Path(__file__).parent
_SOURCES_PATH = _DIR / "sources.yaml"
_AUTHORITY_PATH = _DIR / "authority_map.yaml"


@lru_cache(maxsize=1)
def load_sources() -> list[dict[str, Any]]:
    raw = yaml.safe_load(_SOURCES_PATH.read_text())
    items: list[dict[str, Any]] = list(raw.get("sources") or [])
    for s in items:
        for req in ("id", "name", "url", "kind", "authority_tier"):
            if not s.get(req):
                raise ValueError(f"sources.yaml entry missing {req!r}: {s}")
    return items


@lru_cache(maxsize=1)
def load_authority_map() -> dict[str, Any]:
    raw = yaml.safe_load(_AUTHORITY_PATH.read_text())
    return {
        "routes": list(raw.get("routes") or []),
        "topic_routes": list(raw.get("topic_routes") or []),
    }


def get(source_id: str) -> Optional[dict[str, Any]]:
    return next((s for s in load_sources() if s.get("id") == source_id), None)


def expand_ids(ids: list[str]) -> list[dict[str, Any]]:
    """Turn a list of source-ids into the full source records."""
    return [s for s in (get(i) for i in ids) if s]


def find_for_state(state_code: str) -> list[dict[str, Any]]:
    sc = (state_code or "").upper()
    return [s for s in load_sources() if (s.get("state_code") or "").upper() == sc]


def find_by_kind(kind: str) -> list[dict[str, Any]]:
    return [s for s in load_sources() if s.get("kind") == kind]


def kinds() -> list[str]:
    return sorted({s.get("kind") for s in load_sources() if s.get("kind")})


def jurisdictions() -> list[str]:
    return sorted({s.get("jurisdiction") for s in load_sources() if s.get("jurisdiction")})


# ------------------------------------------------------------------ ROUTING

def route_for_need(need_substring: str, jurisdiction: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Match the routing table by need text OR keywords. Returns matching routes
    with their primary/secondary sources expanded into full records.

    Matching rules:
      - empty `need_substring` -> match all (subject to jurisdiction filter)
      - otherwise: match if substring appears in `need` OR if any token in
        `need_substring` matches an entry in `keywords` (case-insensitive,
        substring on each side).
    """
    want = (need_substring or "").lower().strip()
    want_tokens = [t for t in want.replace(",", " ").split() if t]

    out: list[dict[str, Any]] = []
    for r in load_authority_map()["routes"]:
        if jurisdiction and r.get("for_jurisdiction") not in ("ANY", jurisdiction):
            continue

        if want:
            need_text = (r.get("need") or "").lower()
            keywords = [str(k).lower() for k in (r.get("keywords") or [])]
            hit = (
                want in need_text
                or any(tok in need_text for tok in want_tokens)
                or any(
                    tok == kw or tok in kw or kw in tok
                    for tok in want_tokens
                    for kw in keywords
                )
            )
            if not hit:
                continue

        out.append({
            "need": r["need"],
            "for_jurisdiction": r.get("for_jurisdiction"),
            "why": r.get("why"),
            "keywords": r.get("keywords") or [],
            "primary": expand_ids(r.get("primary") or []),
            "secondary": expand_ids(r.get("secondary") or []),
        })
    return out


def route_for_topic(legal_topic: str, jurisdiction: Optional[str] = None,
                    state_code: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    Look up the full authoritative ladder for one of our normalized
    legal_topics — primary statute (per state), case-law source, statistics
    source, plus an authority note.
    """
    target = (legal_topic or "").lower().strip()
    for tr in load_authority_map()["topic_routes"]:
        if (tr.get("legal_topic") or "").lower() != target:
            continue
        per_state = tr.get("primary_statute_per_state") or {}
        sc = (state_code or "").upper() or None
        statute_id = per_state.get(sc) if sc else None

        return {
            "legal_topic": tr["legal_topic"],
            "description": tr.get("description"),
            "authority_note": tr.get("authority_note"),
            "primary_statute": get(statute_id) if statute_id else None,
            "primary_statute_per_state": {
                k: get(v) for k, v in per_state.items()
            },
            "case_law": get(tr.get("case_law")) if tr.get("case_law") else None,
            "statistics": get(tr.get("statistics")) if tr.get("statistics") else None,
        }
    return None
