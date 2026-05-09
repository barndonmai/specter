#!/usr/bin/env python3
"""
Pretty-print Specter API responses for the terminal.

Usage:
    python scripts/pretty.py health
    python scripts/pretty.py factors
    python scripts/pretty.py lookup "Cal. Veh. Code § 23152(a)"
    python scripts/pretty.py search "drunk driving" --state CA --factor "DUI/DWI" --k 5
    python scripts/pretty.py ask "what statutes apply when someone runs a red light"

Or if you just want a quick top-K view from any /search call:
    python scripts/pretty.py raw '{...json...}'
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

# Make the repo root importable so `from api.pi_brief import ...` works when
# this script is invoked as `python scripts/pretty.py ...`. Without this,
# Python only puts scripts/ on sys.path and any cross-package import fails.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx  # noqa: E402  (intentional after sys.path tweak)

API = os.getenv("SPECTER_API", "http://127.0.0.1:8000")

# --- ANSI ---------------------------------------------------------------
RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
UND     = "\033[4m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
GREY    = "\033[90m"

NO_COLOR = not sys.stdout.isatty() or os.getenv("NO_COLOR")
def c(code: str, s: str) -> str:
    return s if NO_COLOR else f"{code}{s}{RESET}"


def hr(char: str = "─", color: str = GREY) -> str:
    try:
        width = os.get_terminal_size().columns
    except OSError:
        width = 80
    return c(color, char * min(width, 100))


def header(title: str) -> None:
    print()
    print(hr("━", CYAN))
    print(c(BOLD + CYAN, f"  {title}"))
    print(hr("━", CYAN))


def kv(label: str, value, label_color: str = MAGENTA) -> None:
    print(f"  {c(label_color, label.ljust(14))} {value}")


def quote(text: str, max_chars: int = 220) -> str:
    """Wrap and indent statute text for readability."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    wrapped = textwrap.fill(text, width=88, initial_indent="  ", subsequent_indent="  ")
    return c(GREY, wrapped)


def score_bar(score: float, width: int = 20) -> str:
    score = max(0.0, min(1.0, float(score)))
    filled = int(round(score * width))
    bar = "█" * filled + "░" * (width - filled)
    color = GREEN if score >= 0.6 else (YELLOW if score >= 0.4 else RED)
    return c(color, bar) + c(DIM, f"  {score:.3f}")


# --- renderers ----------------------------------------------------------

def render_health(data: dict) -> None:
    header("HEALTH")
    ok = data.get("ok")
    kv("status",     c(GREEN, "OK") if ok else c(RED, "DOWN"))
    kv("collection", c(BOLD, str(data.get("collection"))))
    kv("count",      c(BOLD + YELLOW, str(data.get("count"))))


def render_factors(data: dict) -> None:
    header("CONTRIBUTING FACTORS  (17)")
    factors = data.get("factors", [])
    for f in factors:
        print(f"  {c(MAGENTA, '•')} {f}")


def render_record(rec: dict, idx: int | None = None) -> None:
    cite = rec.get("citation") or rec.get("id")
    title = rec.get("title") or ""
    factors = rec.get("factors_csv") or ""
    state = rec.get("state_code") or ""
    score = rec.get("score")
    url = rec.get("source_url") or ""
    text = rec.get("text") or ""
    pi = rec.get("pi_relevant")

    bullet = f"{c(BOLD + CYAN, str(idx) + '.')}  " if idx is not None else "  "
    line1 = f"{bullet}{c(BOLD, cite)}"
    if state:
        line1 += "  " + c(BLUE, f"[{state}]")
    if title:
        line1 += "  " + c(DIM, title)
    print(line1)

    if factors:
        print(f"     {c(MAGENTA, 'factors')}  {factors}")
    if score is not None:
        print(f"     {c(MAGENTA, 'score  ')}  {score_bar(score)}")
    if pi is True:
        print(f"     {c(MAGENTA, 'pi     ')}  {c(GREEN, 'yes')}")
    print(quote(text))
    if url:
        print(f"     {c(GREY + UND, url)}")
    print()


def render_lookup(data: dict) -> None:
    header(f"LOOKUP  {data.get('citation', '')}")
    render_record(data)


def render_search(data: dict) -> None:
    q = data.get("query", "")
    filters = data.get("filters") or {}
    results = data.get("results") or []
    header(f"SEARCH  '{q}'")
    parts = []
    for k, v in filters.items():
        if v is None or v is False:
            continue
        parts.append(f"{c(MAGENTA, k)}={c(BOLD, str(v))}")
    if parts:
        print("  " + "   ".join(parts))
    print(c(DIM, f"  {len(results)} result(s)"))
    print()
    if not results:
        print(c(YELLOW, "  (no results)"))
        return
    for i, r in enumerate(results, 1):
        render_record(r, idx=i)


def render_ask(data: dict) -> None:
    header(f"ASK  '{data.get('question', '')}'")
    hits = data.get("hits") or []
    print(c(DIM, f"  {len(hits)} hit(s)"))
    print()
    for i, r in enumerate(hits, 1):
        render_record(r, idx=i)


# --- commands -----------------------------------------------------------

def cmd_health(_args):
    r = httpx.get(f"{API}/healthz", timeout=10).json()
    render_health(r)


def cmd_factors(_args):
    r = httpx.get(f"{API}/factors", timeout=10).json()
    render_factors(r)


def cmd_lookup(args):
    r = httpx.get(f"{API}/lookup", params={"citation": args.citation}, timeout=30)
    if r.status_code != 200:
        print(c(RED, f"error {r.status_code}: {r.text}"))
        sys.exit(1)
    record = r.json()
    if getattr(args, "brief", False):
        # PI-lawyer brief format: bluebook + pull quote + NPS analysis +
        # defenses + evidence + Specter notes. Sourced from
        # api.pi_brief which joins the record with data/pi_playbook.yaml.
        try:
            from api.pi_brief import build_brief, render_ansi
            print(render_ansi(build_brief(record)))
            return
        except Exception as e:  # noqa: BLE001
            print(c(YELLOW, f"[brief] render failed, falling back to default: {e}"))
    render_lookup(record)


def cmd_search(args):
    params = {"q": args.query, "k": args.k}
    if args.state:
        params["state"] = args.state
    if args.factor:
        params["factor"] = args.factor
    if args.pi_only:
        params["pi_only"] = "true"
    r = httpx.get(f"{API}/search", params=params, timeout=60)
    if r.status_code != 200:
        print(c(RED, f"error {r.status_code}: {r.text}"))
        sys.exit(1)
    render_search(r.json())


def cmd_ask(args):
    body = {"question": args.question, "k": args.k}
    if args.state:
        body["state"] = args.state
    if args.factor:
        body["factor"] = args.factor
    r = httpx.post(f"{API}/ask", json=body, timeout=60)
    if r.status_code != 200:
        print(c(RED, f"error {r.status_code}: {r.text}"))
        sys.exit(1)
    render_ask(r.json())


def cmd_raw(args):
    data = json.loads(args.json)
    if "results" in data:
        render_search(data)
    elif "hits" in data:
        render_ask(data)
    elif "factors" in data and isinstance(data["factors"], list):
        render_factors(data)
    elif "ok" in data:
        render_health(data)
    else:
        render_record(data)


# --- entry --------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Pretty-print Specter API responses")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health").set_defaults(func=cmd_health)
    sub.add_parser("factors").set_defaults(func=cmd_factors)

    pl = sub.add_parser("lookup")
    pl.add_argument("citation")
    pl.add_argument(
        "--brief",
        action="store_true",
        help="Render the PI-lawyer brief format (bluebook citation, pull quote, NPS analysis, defenses, evidence) instead of the default record view.",
    )
    pl.set_defaults(func=cmd_lookup)

    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("--state", default=None)
    ps.add_argument("--factor", default=None)
    ps.add_argument("--pi-only", action="store_true")
    ps.add_argument("--k", type=int, default=5)
    ps.set_defaults(func=cmd_search)

    pa = sub.add_parser("ask")
    pa.add_argument("question")
    pa.add_argument("--state", default=None)
    pa.add_argument("--factor", default=None)
    pa.add_argument("--k", type=int, default=5)
    pa.set_defaults(func=cmd_ask)

    pr = sub.add_parser("raw")
    pr.add_argument("json", help="JSON blob to render")
    pr.set_defaults(func=cmd_raw)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
