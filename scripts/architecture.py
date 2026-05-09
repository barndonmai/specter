#!/usr/bin/env python3
"""
Visualize the ENTIRE Specter architecture in your terminal.

Inspects the repo + the live system to show:
  • The full pipeline (CSV -> seed -> tag -> embed -> serve)
  • Every directory + what's inside it (live counts, sizes, line counts)
  • External services and how they hook in
  • Make targets and what each does
  • The complete request flow for /search, /lookup, /ask, /authority
  • Where every layer's code lives

Usage:
    make visualize-entire-architecture-project
    PYTHONPATH=. .venv/bin/python scripts/architecture.py
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------- ANSI

NO_COLOR = not sys.stdout.isatty() or os.getenv("NO_COLOR")
def c(code, s):  # noqa: E704
    return s if NO_COLOR else f"{code}{s}\033[0m"

B = "\033[1m"; D = "\033[2m"; UND = "\033[4m"
RED = "\033[31m"; GN = "\033[32m"; YL = "\033[33m"
BL = "\033[34m"; MG = "\033[35m"; CY = "\033[36m"; GREY = "\033[90m"


def width():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


def hr(ch="─", w=None):
    return ch * (w or min(width(), 100))


def header(title, color=CY):
    print()
    print(c(color + B, hr("━")))
    print(c(color + B, f"  {title}"))
    print(c(color + B, hr("━")))


def sub(title, color=BL):
    print()
    print(c(color + B, f"┌─ {title} ─" + "─" * max(0, 80 - len(title))))


# ---------------------------------------------------------------- repo introspection

def file_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8", errors="ignore"))
    except Exception:
        return 0


def file_size(path: Path) -> str:
    try:
        n = path.stat().st_size
        if n >= 1024 * 1024:
            return f"{n / 1024 / 1024:.1f}M"
        if n >= 1024:
            return f"{n / 1024:.1f}K"
        return f"{n}B"
    except Exception:
        return "?"


def list_dir(p: Path, exts=None, exclude_prefixes=(".",)) -> list[Path]:
    if not p.is_dir():
        return []
    out = []
    for f in sorted(p.iterdir()):
        if any(f.name.startswith(pre) for pre in exclude_prefixes):
            continue
        if exts and f.is_file() and f.suffix not in exts:
            continue
        out.append(f)
    return out


def count_eval_csvs() -> dict:
    out = {}
    for f in sorted((ROOT / "data").glob("eval-*-vehicle-code.csv")):
        try:
            n = sum(1 for _ in f.open()) - 1
        except Exception:
            n = 0
        out[f.stem] = n
    return out


def count_json(p: Path) -> int:
    if not p.exists():
        return 0
    try:
        import json
        data = json.loads(p.read_text())
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0


def make_targets() -> list[tuple[str, str]]:
    mk = ROOT / "Makefile"
    if not mk.exists():
        return []
    pat = re.compile(r"^([a-zA-Z][\w-]*):", re.MULTILINE)
    targets = []
    for m in pat.finditer(mk.read_text()):
        name = m.group(1)
        if name in ("PHONY",):
            continue
        # Find an inline comment on the line before the target if any
        start = m.start()
        prev_lines = mk.read_text()[:start].splitlines()
        desc = ""
        for line in reversed(prev_lines[-4:] if len(prev_lines) >= 4 else prev_lines):
            line = line.strip()
            if line.startswith("#"):
                desc = line.lstrip("# ").strip()
                break
            if line == "":
                continue
            break
        targets.append((name, desc))
    # de-dup while preserving order
    seen = set()
    deduped = []
    for n, d in targets:
        if n in seen:
            continue
        seen.add(n)
        deduped.append((n, d))
    return deduped


# ---------------------------------------------------------------- live system

def chroma_stats() -> dict:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from api import chroma_store
        coll = chroma_store.get_collection()
        return {"name": coll.name, "count": coll.count(), "ok": True}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def wiki_stats() -> dict | None:
    try:
        import wiki
        return {
            "sources":   len(wiki.load_sources()),
            "kinds":     len(wiki.kinds()),
            "needs":     len(wiki.load_authority_map().get("routes", [])),
            "topic_routes": len(wiki.load_authority_map().get("topic_routes", [])),
        }
    except Exception:
        return None


# ============================================================================ MAIN

def main() -> None:
    # --------------------------------------------------------------- TITLE

    print()
    print(c(CY + B, hr("━")))
    print(c(CY + B, "    ░██████╗██████╗░███████╗░█████╗░████████╗███████╗██████╗░"))
    print(c(CY + B, "    ██╔════╝██╔══██╗██╔════╝██╔══██╗╚══██╔══╝██╔════╝██╔══██╗"))
    print(c(CY + B, "    ╚█████╗░██████╔╝█████╗░░██║░░╚═╝░░░██║░░░█████╗░░██████╔╝"))
    print(c(CY + B, "    ░╚═══██╗██╔═══╝░██╔══╝░░██║░░██╗░░░██║░░░██╔══╝░░██╔══██╗"))
    print(c(CY + B, "    ██████╔╝██║░░░░░███████╗╚█████╔╝░░░██║░░░███████╗██║░░██║"))
    print(c(CY + B, "    ╚═════╝░╚═╝░░░░░╚══════╝░╚════╝░░░░╚═╝░░░╚══════╝╚═╝░░╚═╝"))
    print()
    print(c(B, "    EvenUp x OpenClaw Hackathon — Legal Research Agent"))
    print(c(D, "    A live introspection of the entire project architecture."))
    print(c(CY + B, hr("━")))

    # --------------------------------------------------------------- LIVE

    chr_ = chroma_stats()
    wiki = wiki_stats()
    csvs = count_eval_csvs()
    raw  = list_dir(ROOT / "data" / "raw", exts={".json"})
    tagged = list_dir(ROOT / "data" / "tagged", exts={".json"})

    print()
    print(c(B, "  📊 Live system snapshot"))
    print(c(GREY, "  " + "─" * 80))
    if chr_.get("ok"):
        print(f"  {c(MG, 'Chroma:')} {c(B + YL, str(chr_['count']))} records in collection {c(B, chr_['name'])}")
    else:
        print(f"  {c(MG, 'Chroma:')} {c(RED, 'not loadable: ' + chr_.get('err', '?'))}")
    if wiki:
        print(f"  {c(MG, 'Wiki:')}   {c(B + YL, str(wiki['sources']))} sources, "
              f"{c(B + YL, str(wiki['needs']))} need-routes, {c(B + YL, str(wiki['topic_routes']))} topic-routes")
    print(f"  {c(MG, 'CSVs:')}   {c(B + YL, str(len(csvs)))} state CSVs ({sum(csvs.values())} total rows)")
    for stem, n in csvs.items():
        st = stem.replace("eval-", "").replace("-vehicle-code", "").upper()
        print(f"           {st:<3s}  {n:>4d} rows  ({stem}.csv)")
    print(f"  {c(MG, 'Raw:')}    {len(raw)} JSON files in data/raw  ({sum(count_json(p) for p in raw)} records)")
    print(f"  {c(MG, 'Tagged:')} {len(tagged)} JSON files in data/tagged  ({sum(count_json(p) for p in tagged)} records)")

    # --------------------------------------------------------------- PIPELINE

    header("THE PIPELINE  —  CSV ➜ Chroma ➜ API ➜ User", CY)

    pipeline = f"""
   {c(YL, '①')}                    {c(YL, '②')}                        {c(YL, '③')}                {c(YL, '④')}                  {c(YL, '⑤')}
  ┌─────────┐         ┌─────────────┐         ┌─────────────┐    ┌────────────┐    ┌────────────┐
  │  CSV    │   make  │  Pydantic   │   make  │  Claude     │    │  Voyage    │    │  Chroma    │
  │ data/   │  seed   │  StatuteRec │  tag    │  Haiku      │    │  law-2     │    │  vector DB │
  │ eval-*  │ ───────►│  data/raw/  │ ───────►│  17-cat tag │───►│  1024-dim  │───►│ persist    │
  │  .csv   │         │  *.json     │         │ data/tagged │    │  embedding │    │  .chroma/  │
  └─────────┘         └─────────────┘         └─────────────┘    └────────────┘    └─────┬──────┘
                                                                                        │
                                                                                        │
                            {c(YL, '⑥')}                            {c(YL, '⑦')}                       │
                  ┌────────────────────┐         ┌──────────────────┐                  │
                  │  Claude enrichment │   make  │  metadata-only   │                  │
                  │  legal_topic +     │  enrich │  collection      │ ◄────────────────┘
                  │  jurisdiction_norm │ ───────►│  .update()       │  (preserves
                  │  document_type +   │         │  (NO re-embed)   │   embeddings)
                  │  authority_source  │         └────────┬─────────┘
                  └────────────────────┘                  │
                                                          ▼
                                                   ┌──────────────┐
                                                   │  FastAPI     │     {c(GN, '──► /lookup')}
                                                   │  api/main.py │     {c(GN, '──► /search')}
                                                   │  port :8000  │     {c(GN, '──► /ask')}
                                                   │              │     {c(MG, '──► /factors')}
                                                   │              │     {c(MG, '──► /topics')}
                                                   │              │     {c(YL, '──► /sources')}
                                                   │              │     {c(YL, '──► /authority')}
                                                   └──────┬───────┘
                                                          ▼
                                       ┌─────────────────────────────────┐
                                       │     OpenClaw agent + WhatsApp   │
                                       └─────────────────────────────────┘
"""
    print(pipeline)

    # --------------------------------------------------------------- USER DATA FLOW

    header("USER DATA FLOW  —  what happens when a paralegal asks a question", MG)

    user_flow = f"""
   {c(YL + B, '①  USER  (paralegal / attorney on WhatsApp)')}
        “my client got rear-ended by a drunk driver in California…”
                                  │
                                  │  WhatsApp Business API
                                  ▼
   {c(YL + B, '③  OpenClaw agent')}                            ({c(D, 'separate process')})
        • SOUL.md persona  • skills loaded from openclaw/skills/
        • Claude reasons about the request
        • picks the right skill: harvester-query / pi_brief_format / …
                                  │
                                  │  HTTP
                                  ▼
   {c(YL + B, '④  Specter API')}  ({c(D, 'this repo, FastAPI on :8000')})
        • GET  /search?q=...&legal_topic=...&state=CA
        • POST /ask  {{ question, legal_topic?, state? }}
        • GET  /authority?legal_topic=...&state=...
                                  │
                ____________________|____________________
               │                                       │
               ▼                                       ▼
   {c(BL + B, '⑤  Voyage API')}                          {c(GN + B, '⑤  Chroma local')}
      • embed query → 1024-dim vec               • metadata-only ops are FREE
      • (RPM-limited, cached)                    • cosine-similarity over 384 vecs
               │                                       │
               └──────────────────────────────────────────────┘
                                  │  top-K {{citation, text, score, source_url,
                                  │           legal_topic, factors_csv, ...}}
                                  ▼
   {c(MG + B, '⑥  Optional enrichment paths')}
        • {c(B, 'authority routing')}      → wiki/  →  “which source for what”
        • {c(B, 'PI brief format')}        → api/pi_brief.py  → attorney-shaped output
        • {c(B, 'web fallback')}           → if Harvester misses, live-fetch authoritative URL
                                  │
                                  ▼
   {c(YL + B, '⑦  OpenClaw agent')}
        • composes a friendly reply citing real source URLs
        • (SOUL rule: every citation MUST carry a verifiable URL)
                                  │
                                  ▼
   {c(YL + B, '⑧  USER receives:')}
        “Three CA statutes apply: § 23152 (DUI), § 23153 (DUI w/ injury),
         § 23152(c) (drug DUI). Source: leginfo.legislature.ca.gov.
         For case-law workup, CourtListener has interpretations of § 23152.”

   {c(GREY, 'Total round-trip:')} ~{c(B, '300–800ms')} {c(GREY, 'when Voyage card is on file (RPM unblocks).')}
   {c(GREY, 'On free tier (3 RPM):')} {c(B, 'first 3 queries fast, 4th+ blocks briefly.')}
"""
    print(user_flow)

    # --------------------------------------------------------------- DIRECTORIES

    header("REPO LAYOUT  —  every directory, live counts", GN)

    dirs = [
        ("data/",
         "CSVs (input) and per-state JSON outputs of the pipeline.",
         [
             ("eval-*-vehicle-code.csv", "Released + curated state evaluation CSVs (input)"),
             ("raw/<state>-eval.json",   "After `make seed` — Pydantic-validated records"),
             ("tagged/<state>-eval.json", "After `make tag` — factor labels filled in"),
         ]),
        ("harvester/",
         "Schema and ingestion contracts.",
         [
             ("schema.py",          "StatuteRecord (Pydantic) + 17 contributing-factor categories"),
             ("scrapers/_base.py",  "polite httpx client + write_records helper"),
             ("scrapers/<state>.py", "per-jurisdiction scraper stubs"),
         ]),
        ("tagger/",
         "LLM-driven enrichment passes.",
         [
             ("prompt.py", "System prompt for the 17-cat factor classifier"),
             ("tag.py",    "Threaded batch tagger over data/raw → data/tagged"),
             ("enrich.py", "Adds legal_topic / topic_confidence / jurisdiction_norm / "
                           "document_type / authority_source to existing Chroma rows "
                           "(preserves embeddings)"),
         ]),
        ("api/",
         "FastAPI service surface — what every other layer talks to.",
         [
             ("main.py",         "Endpoint definitions: /healthz /factors /topics /lookup /search /ask /sources /authority"),
             ("chroma_store.py", "Chroma wrapper + factor-flag filtering trick + multi-key $and"),
             ("voyage_embed.py", "Lazy Voyage client + token-bucket RPM limiter + LRU cache + 429 retry"),
             ("pi_brief.py",     "Brief formatter — turns Harvester records into PI-lawyer briefs"),
         ]),
        ("wiki/",
         "Authoritative-source wiki (the hackathon bonus deliverable).",
         [
             ("sources.yaml",         "Catalog of 22 trusted sources across 7 kinds"),
             ("authority_map.yaml",   "Routing table: 'which sources for what'"),
             ("__init__.py",          "Loaders + route_for_need / route_for_topic"),
         ]),
        ("scripts/",
         "Operator + demo CLI.",
         [
             ("seed_from_eval.py", "Per-state CSV → data/raw/<state>-eval.json"),
             ("load_chroma.py",    "data/tagged/*.json → Chroma w/ Voyage embeddings (incremental)"),
             ("pretty.py",         "ANSI-rendered API client (search/lookup/ask/sources/authority)"),
             ("browse.py",         "Curses TUI to scroll every record, lawyer/engineer toggle"),
             ("schema.py",         "Live introspection of every field + distribution (`make schema`)"),
             ("architecture.py",   "THIS FILE — full architecture visualizer"),
             ("case_demo.sh",      "Anaheim phantom-vehicle showcase demo (`make demo-big-ass-query`)"),
         ]),
        ("evals/",
         "Hackathon scoring harness.",
         [
             ("run_eval.py", "Runs released CA CSV against the live API; reports citation lookup + factor retrieval@k"),
         ]),
        ("openclaw/skills/",
         "Skills loaded by the OpenClaw / WhatsApp side.",
         [
             ("web_fallback/",       "Live web fetch for unindexed queries"),
             ("harvester-query/",    "Wraps /search for the agent"),
             ("citation-format/",    "Forces every cite to include a source URL"),
             ("pi_brief_format/",    "Renders PI-style briefs from search hits"),
         ]),
        ("sources/",
         "Hackathon reference material (read-only context for the agent).",
         [
             ("Hackathon Prep.pdf",         "Brief PDF"),
             ("Scoring",                    "Brief / scoring rubric (text)"),
             ("eval-ca-vehicle-code.csv",   "Released eval CSV — same as data/eval-ca-vehicle-code.csv"),
         ]),
    ]

    for path, desc, items in dirs:
        p = ROOT / path.rstrip("/")
        present = "✓" if p.exists() else "·"
        col = GN if p.exists() else GREY
        print(f"\n  {c(col + B, present + ' ' + path):<28s}  {c(D, desc)}")
        for fname, fdesc in items:
            print(f"      {c(MG, fname):<32s}  {c(D, fdesc)}")

    # --------------------------------------------------------------- TOP-LEVEL FILES

    sub("Top-level files", BL)
    top = [
        ("Makefile",         "All operator + demo targets"),
        ("requirements.txt", "Python deps (FastAPI, Chroma, Voyage, Anthropic, pyyaml, ...)"),
        (".env / .env.example", "VOYAGE_API_KEY, ANTHROPIC_API_KEY, VOYAGE_RPM, etc."),
        ("README.md",        "Project intro + quickstart"),
        ("SOUL.md",          "Agent persona / behavior contracts (OpenClaw side)"),
    ]
    for fname, fdesc in top:
        p = ROOT / fname.split(" ")[0]
        present = "✓" if p.exists() else "·"
        col = GN if p.exists() else GREY
        size = file_size(p) if p.exists() else ""
        print(f"  {c(col, present)}  {c(B, fname):<22s}  {c(D, size):<8s}  {c(D, fdesc)}")

    # --------------------------------------------------------------- EXTERNAL SERVICES

    header("EXTERNAL SERVICES  —  what we call out to", YL)

    services = [
        ("Voyage AI",   "voyage-law-2",        "1024-dim legal embeddings",
         "VOYAGE_API_KEY", "rate-limited inside api/voyage_embed.py (RPM token bucket)"),
        ("Anthropic",   "claude-haiku-4-5",    "factor tagging + topic enrichment",
         "ANTHROPIC_API_KEY", "called from tagger/tag.py and tagger/enrich.py"),
        ("Chroma",      "PersistentClient",    "local vector DB (./.chroma/)",
         "(no key)", "embeddings + metadata + cosine search"),
        ("OpenClaw",    "WhatsApp agent",      "user-facing chat surface",
         "(separate process)", "calls our /search /lookup /ask via the OpenClaw skills"),
    ]
    hdr = f"  {'service':<14}{'model/role':<22}{'purpose':<32}"
    print(c(B, hdr))
    print(c(GREY, "  " + "─" * 82))
    for name, model, purpose, key, note in services:
        print(f"  {c(YL + B, name):<23s}{c(MG, model):<31s}{purpose:<32s}")
        print(f"      {c(D, 'env: ' + key)}")
        print(f"      {c(D, '↳  ' + note)}")
        print()

    # --------------------------------------------------------------- MAKE TARGETS

    header("MAKE TARGETS  —  what each one does", BL)
    targets = make_targets()
    for name, desc in targets:
        print(f"  {c(GN + B, 'make ' + name):<34s}  {c(D, desc)}")

    # --------------------------------------------------------------- REQUEST FLOWS

    header("REQUEST FLOW  —  what happens on each endpoint", MG)

    flow = f"""
  {c(B + GN, 'GET /search?q=…&legal_topic=…&state=…')}
    └─► api/main.py  validates query + filters
        └─► api/voyage_embed.py
            └─► (RPM limiter blocks if needed)
                └─► (LRU cache hit?  return cached vec)  ◄────────── FREE
                    └─► (cache miss) Voyage API embed(query)
                        └─► return 1024-dim vector
        └─► api/chroma_store.py.search(vec, where={{...}})
            └─► Chroma cosine-similarity over 384 vectors
                └─► return top-K with metadata (incl. score, source_url)

  {c(B + GN, 'GET /lookup?citation=…')}
    └─► api/main.py
        └─► chroma_store.lookup_by_citation(cite)
            └─► Chroma metadata filter   (NO Voyage call)
                └─► return single record

  {c(B + GN, 'POST /ask  {{ "question": …, … }}')}
    └─► api/main.py
        └─► same as /search but JSON-bodied (chat-agent friendly)

  {c(B + MG, 'GET /authority?legal_topic=…&state=…')}
    └─► api/main.py
        └─► wiki/__init__.py.route_for_topic(topic, state)
            └─► resolves source IDs → full source records
                └─► returns ladder: primary statute + case law + stats + note

  {c(B + MG, 'GET /sources?state=…&kind=…')}
    └─► api/main.py
        └─► wiki.load_sources() filtered by state / kind
"""
    print(flow)

    # --------------------------------------------------------------- DEPENDENCIES

    header("ENRICHMENT LAYERS  —  the abstraction stack", CY)

    print(f"""
  Each layer ADDS structure on top of the previous one.
  None overwrite original fields. None re-embed.

  {c(GREY, '─' * 90)}

   {c(B + BL, 'LAYER A')}  Raw CSV        → state-specific labels (40+ messy strings)
                              ↓                  e.g. "Speeding", "Wireless Telephone",
                              ↓                       "Texting While Driving", ...
                              ↓
   {c(B + BL, 'LAYER B')}  17-cat schema  → official contributing factors
                              ↓                  e.g. "DUI/DWI", "Improper Turning",
                              ↓                       "Driving Too Fast For Conditions"
                              ↓
   {c(B + BL, 'LAYER C')}  Normalized     → 21 attorney-friendly topics
              {c(D, '(this file)')}             e.g. "DUI-related behavior", "speeding",
                                                 "distracted driving", "hit and run"
                              ↓
   {c(B + BL, 'LAYER D')}  Authority map  → "which source is authoritative for what"
                                           e.g. DUI-CA → ca-leginfo + courtlistener
                                                       + nhtsa-fars + authority note

   {c(GREY, 'Net effect: a single semantic query')}  {c(B + GN, '"drunk driving in California"')}
   {c(GREY, 'resolves to:')}
       1.  {c(B, 'normalized topic:')}     DUI-related behavior
       2.  {c(B, 'matching statutes:')}    Cal. Veh. Code §§ 23152, 23153
       3.  {c(B, 'authoritative source:')} leginfo.legislature.ca.gov
       4.  {c(B, 'where to find cases:')}  courtlistener.com
       5.  {c(B, 'where to find stats:')}  nhtsa.gov/.../fars
""")

    # --------------------------------------------------------------- TL;DR

    header("ONE-PARAGRAPH TL;DR", CY)
    chr_count = chr_.get("count", "?") if chr_.get("ok") else "?"
    n_sources = wiki['sources'] if wiki else "?"
    print(f"""
  Specter ingests U.S. motor-vehicle statutes from per-state CSVs, validates
  them via a Pydantic schema, tags them with the 17 official contributing-
  factor categories, embeds the text with {c(B, 'voyage-law-2')} (1024-dim cosine),
  and stores everything in a local {c(B, 'Chroma')} collection of {c(B, str(chr_count))} records across
  6 jurisdictions. A second Claude pass enriches every row with a normalized
  {c(B, 'legal_topic')}, jurisdiction, document type, and authority source — without
  touching the embeddings. A FastAPI service exposes 8 endpoints for citation
  lookup, semantic search with structured filters, and authority routing
  against a curated wiki of {c(B, str(n_sources))} sources. The whole thing is operated by 8
  Make targets and demoed by a `case_demo.sh` showpiece that walks an Anaheim
  phantom-vehicle case end to end. The OpenClaw + WhatsApp side calls these
  endpoints from skills in `openclaw/skills/`. Total stack: Python + FastAPI
  + Chroma + Voyage + Anthropic + a YAML wiki, glued by a Makefile.
""")


if __name__ == "__main__":
    main()
