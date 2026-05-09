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
    header("CONTRIBUTING FACTORS  (raw, 17-cat schema)")
    factors = data.get("factors", [])
    for f in factors:
        print(f"  {c(MAGENTA, '•')} {f}")


def render_topics(data: dict) -> None:
    header("LEGAL TOPICS  (normalized semantic abstraction)")
    topics = data.get("topics", [])
    for t in topics:
        print(f"  {c(BLUE, '•')} {t}")


KIND_COLOR = {
    "primary_statute":  GREEN,
    "case_law":         CYAN,
    "bar_association":  MAGENTA,
    "court_system":     YELLOW,
    "federal_dataset":  BLUE,
    "federal_agency":   BLUE,
    "state_agency":     YELLOW,
}

TIER_BADGE = {
    "primary":   c(GREEN, "● primary  "),
    "secondary": c(YELLOW, "● secondary"),
    "tertiary":  c(GREY, "● tertiary "),
}


def render_sources(data: dict) -> None:
    header(f"AUTHORITATIVE-SOURCE WIKI  ({data.get('count', 0)} sources)")
    print(c(DIM, f"  Kinds:        {', '.join(data.get('kinds', []))}"))
    print(c(DIM, f"  Jurisdictions: {', '.join(data.get('jurisdictions', []))}"))
    print()

    # Group by kind
    from collections import defaultdict
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for s in data.get("sources", []):
        by_kind[s.get("kind", "other")].append(s)

    for kind in sorted(by_kind.keys()):
        kc = KIND_COLOR.get(kind, BOLD)
        print(c(kc + BOLD, f"── {kind} ({len(by_kind[kind])}) "))
        for s in by_kind[kind]:
            tier = TIER_BADGE.get(s.get("authority_tier", ""), "")
            jur = s.get("jurisdiction") or "—"
            official = c(GREEN, "✓ official") if s.get("is_official") else c(GREY, "  unofficial")
            print(f"  {tier}  {c(BOLD, s['name'])}  {c(DIM, '[' + jur + ']')}  {official}")
            print(f"             {c(GREY + UND, s['url'])}")
            covers = s.get("covers") or []
            if covers:
                for cov in covers[:3]:
                    print(f"             {c(DIM, '• ' + cov)}")
            answers = s.get("answers") or []
            if answers:
                print(f"             {c(MAGENTA, 'answers:')}")
                for a in answers[:2]:
                    line = '  "' + a + '"'
                    print(f"             {c(DIM, line)}")
            print()


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

    legal_topic = rec.get("legal_topic")
    topic_conf  = rec.get("topic_confidence")
    doc_type    = rec.get("document_type")
    auth        = rec.get("authority_source")

    if legal_topic:
        tc = f"  {c(DIM, f'(conf {topic_conf:.2f})')}" if topic_conf is not None else ""
        print(f"     {c(BLUE, 'topic  ')}  {c(BOLD, legal_topic)}{tc}")
    if factors:
        print(f"     {c(MAGENTA, 'factors')}  {factors}")
    if doc_type or auth:
        bits = []
        if doc_type:
            bits.append(f"{c(DIM, 'type=')}{doc_type}")
        if auth:
            bits.append(f"{c(DIM, 'auth=')}{auth}")
        print(f"     {c(MAGENTA, 'meta   ')}  {'   '.join(bits)}")
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


def cmd_topics(_args):
    r = httpx.get(f"{API}/topics", timeout=10).json()
    render_topics(r)


def _money(n: int) -> str:
    return "${:,}".format(int(n))


def cmd_organize(args):
    body = {
        "description": args.description,
        "state": args.state,
        "legal_topic": args.legal_topic,
        "k_statutes": args.k_statutes,
        "k_comparables": args.k_comparables,
    }
    r = httpx.post(f"{API}/organize", json=body, timeout=120)
    if r.status_code != 200:
        print(c(RED, f"error {r.status_code}: {r.text}"))
        return
    d = r.json()

    header("📁 ORGANIZER  —  paralegal workspace")
    print(f"  {c(DIM, 'description:')}")
    txt = d['description']
    if len(txt) > 600:
        txt = txt[:600] + "…"
    print(f"  {c(GREY, txt)}")

    # Statutes
    statutes = d.get("statutes", [])
    print()
    print(c(BOLD + GREEN, f"  └─ APPLICABLE STATUTES ({len(statutes)})"))
    for s in statutes:
        print(f"     {c(BOLD, s.get('citation','?'))}  {c(MAGENTA, '['+(s.get('legal_topic') or '?')+']')}")
        text = (s.get('text') or '').strip()
        if len(text) > 160:
            text = text[:160] + "…"
        print(f"       {c(DIM, text)}")
        print(f"       {c(GREY + UND, s.get('source_url') or '')}")
        print()

    # Comparables
    comps = d.get("comparables", {})
    stats = comps.get("stats", {})
    rows = comps.get("comparables", [])
    print(c(BOLD + BLUE, f"  └─ DAMAGES COMPARABLES  (n={stats.get('n',0)})"))
    if stats.get("n"):
        print(f"     {c(MAGENTA, 'min:    ')}{_money(stats.get('min',0))}")
        print(f"     {c(MAGENTA, 'median: ')}{c(BOLD + YELLOW, _money(stats.get('median',0)))}")
        print(f"     {c(MAGENTA, 'mean:   ')}{_money(stats.get('mean',0))}")
        print(f"     {c(MAGENTA, 'max:    ')}{_money(stats.get('max',0))}")
        print()
    for r_ in rows[:5]:
        print(f"     {c(BOLD, r_.get('case_name','?'))}  "
              f"{c(DIM, '['+r_.get('state_code','??')+']')}  "
              f"{c(BOLD + GREEN, _money(r_.get('settlement_amount',0)))}  "
              f"{c(DIM, '('+str(r_.get('year','?'))+', '+r_.get('outcome','?')+')')}")
        print(f"        {c(DIM, r_.get('injury_type',''))}  "
              f"{c(GREY, '—')}  {c(DIM, r_.get('liability_theory',''))}")
        if r_.get("summary"):
            print(f"        {c(DIM, r_['summary'][:140])}")
        if r_.get("source_url"):
            print(f"        {c(GREY + UND, r_['source_url'])}")
        print()

    # Coverage gaps
    cov = d.get("coverage", {})
    score = cov.get("readiness_score")
    if isinstance(score, (int, float)):
        score_color = (GREEN if score >= 0.7 else (YELLOW if score >= 0.4 else RED))
        score_str = c(score_color + BOLD, f"{score*100:.0f}%")
    else:
        score_str = "—"
    print(c(BOLD + YELLOW, f"  └─ COVERAGE  (readiness {score_str})"))
    have = cov.get('have') or []
    miss = cov.get('missing') or []
    unc  = cov.get('uncertain') or []
    nxt  = cov.get('next_actions') or []
    if have:
        print(c(GREEN, f"     have ({len(have)}):"))
        for x in have:
            print(f"       {c(GREEN, '+')} {x}")
    if miss:
        print(c(RED, f"     missing ({len(miss)}):"))
        for x in miss:
            print(f"       {c(RED, '-')} {x}")
    if unc:
        print(c(YELLOW, f"     uncertain ({len(unc)}):"))
        for x in unc:
            print(f"       {c(YELLOW, '?')} {x}")
    if nxt:
        print(c(CYAN + BOLD, f"     next actions:"))
        for x in nxt:
            print(f"       {c(CYAN, '→')} {x}")


def cmd_sources(args):
    params = {}
    if args.state:
        params["state"] = args.state
    if args.kind:
        params["kind"] = args.kind
    r = httpx.get(f"{API}/sources", params=params, timeout=10).json()
    render_sources(r)


def _print_source_brief(s: dict, indent: str = "") -> None:
    if not s:
        return
    tier = TIER_BADGE.get(s.get("authority_tier", ""), "")
    print(f"{indent}{tier}  {c(BOLD, s['name'])}  {c(DIM, '[' + s.get('kind','') + ']')}")
    print(f"{indent}              {c(GREY + UND, s['url'])}")


def cmd_authority(args):
    params = {}
    if args.legal_topic:
        params["legal_topic"] = args.legal_topic
    if args.need:
        params["need"] = args.need
    if args.state:
        params["state"] = args.state
    if args.jurisdiction:
        params["jurisdiction"] = args.jurisdiction

    r = httpx.get(f"{API}/authority", params=params, timeout=10)
    if r.status_code != 200:
        print(c(RED, f"error {r.status_code}: {r.text}"))
        return
    data = r.json()

    if args.legal_topic:
        # Topic-route view
        header(f"AUTHORITY LADDER  '{data['legal_topic']}'")
        if data.get("description"):
            print(f"  {c(DIM, data['description'])}")
        print()
        if args.state and data.get("primary_statute"):
            print(c(BOLD + GREEN, f"  Primary statute (your filter: {args.state}):"))
            _print_source_brief(data["primary_statute"], indent="  ")
        elif data.get("primary_statute_per_state"):
            print(c(BOLD + GREEN, "  Primary statute (per state):"))
            for sc, src in data["primary_statute_per_state"].items():
                if src:
                    print(f"    {c(BOLD + BLUE, sc)}: {src['name']}  {c(GREY + UND, src['url'])}")
        print()
        if data.get("case_law"):
            print(c(BOLD + CYAN, "  Case law:"))
            _print_source_brief(data["case_law"], indent="  ")
            print()
        if data.get("statistics"):
            print(c(BOLD + BLUE, "  Statistics / damages framing:"))
            _print_source_brief(data["statistics"], indent="  ")
            print()
        if data.get("authority_note"):
            print(c(YELLOW, "  ⚠ Authority note:"))
            for line in str(data["authority_note"]).strip().splitlines():
                print(f"    {c(DIM, line)}")
    else:
        # Need-route view
        routes = data.get("routes", [])
        header(f"AUTHORITY ROUTES  ({len(routes)} matched)")
        for r_ in routes:
            print(c(BOLD, f"  • {r_['need']}")
                  + c(DIM, f"   [{r_.get('for_jurisdiction','ANY')}]"))
            for s in r_.get("primary", []):
                _print_source_brief(s, indent="    ")
            for s in r_.get("secondary", []) or []:
                _print_source_brief(s, indent="    ")
            if r_.get("why"):
                why = str(r_["why"]).strip()
                for line in why.splitlines():
                    print(f"    {c(DIM, '→ ' + line)}")
            print()


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
    if args.legal_topic:
        params["legal_topic"] = args.legal_topic
    if args.jurisdiction:
        params["jurisdiction"] = args.jurisdiction
    if args.document_type:
        params["document_type"] = args.document_type
    if args.min_confidence is not None:
        params["min_topic_confidence"] = args.min_confidence
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
    if args.legal_topic:
        body["legal_topic"] = args.legal_topic
    if args.jurisdiction:
        body["jurisdiction"] = args.jurisdiction
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
    sub.add_parser("topics").set_defaults(func=cmd_topics)

    psr = sub.add_parser("sources", help="View the authoritative-source wiki")
    psr.add_argument("--state", default=None, help="Filter by state (CA, TX, FL, PA)")
    psr.add_argument("--kind", default=None, help="Filter by kind (primary_statute, case_law, bar_association, ...)")
    psr.set_defaults(func=cmd_sources)

    pau = sub.add_parser("authority", help="'Which sources are authoritative for what'")
    pau.add_argument("--legal-topic", default=None, help="e.g. 'DUI-related behavior'")
    pau.add_argument("--need", default=None, help="Substring of a research need (e.g. 'damages', 'case law', 'court rules')")
    pau.add_argument("--state", default=None, help="2-letter state code")
    pau.add_argument("--jurisdiction", default=None, help="Full jurisdiction name")
    pau.set_defaults(func=cmd_authority)

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
    ps.add_argument("--legal-topic", default=None)
    ps.add_argument("--jurisdiction", default=None)
    ps.add_argument("--document-type", default=None)
    ps.add_argument("--min-confidence", type=float, default=None)
    ps.add_argument("--pi-only", action="store_true")
    ps.add_argument("--k", type=int, default=5)
    ps.set_defaults(func=cmd_search)

    porg = sub.add_parser("organize", help="Full Organizer workspace for a case description")
    porg.add_argument("description", help="Free-form case description")
    porg.add_argument("--state", default=None)
    porg.add_argument("--legal-topic", dest="legal_topic", default=None)
    porg.add_argument("--k-statutes", dest="k_statutes", type=int, default=8)
    porg.add_argument("--k-comparables", dest="k_comparables", type=int, default=10)
    porg.set_defaults(func=cmd_organize)

    pa = sub.add_parser("ask")
    pa.add_argument("question")
    pa.add_argument("--state", default=None)
    pa.add_argument("--factor", default=None)
    pa.add_argument("--legal-topic", default=None)
    pa.add_argument("--jurisdiction", default=None)
    pa.add_argument("--k", type=int, default=5)
    pa.set_defaults(func=cmd_ask)

    pr = sub.add_parser("raw")
    pr.add_argument("json", help="JSON blob to render")
    pr.set_defaults(func=cmd_raw)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
