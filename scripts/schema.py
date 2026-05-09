#!/usr/bin/env python3
"""
Visualize the ENTIRE Specter schema in your terminal.

Inspects what's actually in Chroma RIGHT NOW — every field, type, cardinality,
value distribution, and how the layers connect (raw factors -> normalized
topics -> authority sources).

Usage:
    python scripts/schema.py
    PYTHONPATH=. .venv/bin/python scripts/schema.py
"""
from __future__ import annotations
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from api import chroma_store
from harvester.schema import CONTRIBUTING_FACTORS
from tagger.enrich import LEGAL_TOPICS

try:
    import wiki as authority_wiki
    HAS_WIKI = True
except Exception:
    HAS_WIKI = False


# ---------------------------------------------------------------- ANSI

NO_COLOR = not sys.stdout.isatty() or os.getenv("NO_COLOR")
def c(code: str, s: str) -> str:
    return s if NO_COLOR else f"{code}{s}\033[0m"

B = "\033[1m"; D = "\033[2m"; UND = "\033[4m"
RED = "\033[31m"; GN = "\033[32m"; YL = "\033[33m"
BL = "\033[34m"; MG = "\033[35m"; CY = "\033[36m"; GREY = "\033[90m"


def term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


def hr(char: str = "─", width: int | None = None) -> str:
    return char * (width or min(term_width(), 100))


def header(title: str, color: str = CY) -> None:
    print()
    print(c(color + B, hr("━")))
    print(c(color + B, f"  {title}"))
    print(c(color + B, hr("━")))


def sub(title: str, color: str = MG) -> None:
    print()
    print(c(color + B, f"┌─ {title} ─" + "─" * max(0, 80 - len(title))))


def kv(label: str, value, indent: str = "  ") -> None:
    print(f"{indent}{c(MG, label.ljust(22))} {value}")


def bar(n: int, total: int, width: int = 30) -> str:
    if total <= 0:
        return ""
    filled = int(round((n / total) * width))
    return c(GN, "█" * filled) + c(GREY, "░" * (width - filled))


def py_type_name(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return f"list[{py_type_name(v[0]) if v else 'any'}]"
    if isinstance(v, dict):
        return "dict"
    return type(v).__name__


# ---------------------------------------------------------------- main

def main() -> None:
    coll = chroma_store.get_collection()
    n = coll.count()
    if n == 0:
        print(c(RED, "Chroma is empty. Run `make seed && make tag && make load` first."))
        return

    res = coll.get(include=["metadatas", "documents", "embeddings"])
    metas: list[dict] = res["metadatas"]
    docs:  list[str] = res["documents"]
    embs:  list[list[float]] = res["embeddings"]

    # ===================================================================
    header("SPECTER SCHEMA — LIVE INSPECTION OF CHROMA DB", CY)
    # ===================================================================

    kv("Collection",       c(B, coll.name))
    kv("Records",          c(B + YL, str(n)))
    kv("Embedding model",  c(B, os.getenv('VOYAGE_MODEL', 'voyage-law-2')))
    dim = (len(embs[0]) if (embs is not None and len(embs) > 0) else None)
    kv("Vector dimension", c(B, str(dim) if dim else "?"))
    kv("Distance metric",  c(B, "cosine"))
    kv("Persist dir",      c(B, os.getenv('CHROMA_PERSIST_DIR', './.chroma')))

    # ===================================================================
    header("ARCHITECTURE LAYERS", BL)
    # ===================================================================

    diagram = f"""
    {c(B, '┌─ LAYER 0: RAW DATA ───────────────────────────────────────────┐')}
    {c(B, '│')}  CSV files in {c(YL, 'data/eval-*.csv')} (per-state evaluation rows)         {c(B, '│')}
    {c(B, '└─────────────────────────────┬─────────────────────────────────┘')}
                                  ▼
    {c(B, '┌─ LAYER 1: STATUTE RECORDS ────────────────────────────────────┐')}
    {c(B, '│')}  StatuteRecord (Pydantic) → {c(YL, 'data/raw/<state>-eval.json')}     {c(B, '│')}
    {c(B, '│')}  Fields: id, citation, code, section, text, source_url, …    {c(B, '│')}
    {c(B, '└─────────────────────────────┬─────────────────────────────────┘')}
                                  ▼
    {c(B, '┌─ LAYER 2: TAGGED RECORDS ─────────────────────────────────────┐')}
    {c(B, '│')}  + contributing_factors[]  ({len(CONTRIBUTING_FACTORS)} canonical categories)         {c(B, '│')}
    {c(B, '│')}  + pi_relevant, confidence                                  {c(B, '│')}
    {c(B, '└─────────────────────────────┬─────────────────────────────────┘')}
                                  ▼
    {c(B, '┌─ LAYER 3: ENRICHED METADATA ──────────────────────────────────┐')}
    {c(B, '│')}  + legal_topic, topic_confidence    ({len(LEGAL_TOPICS)} normalized topics)    {c(B, '│')}
    {c(B, '│')}  + jurisdiction_norm, document_type, authority_source       {c(B, '│')}
    {c(B, '└─────────────────────────────┬─────────────────────────────────┘')}
                                  ▼
    {c(B, '┌─ LAYER 4: VECTOR STORAGE (Chroma) ────────────────────────────┐')}
    {c(B, '│')}  • document = statute text                                  {c(B, '│')}
    {c(B, '│')}  • embedding = Voyage law-2 (1024-dim cosine)               {c(B, '│')}
    {c(B, '│')}  • metadata = all fields above + factor_<name>: bool flags  {c(B, '│')}
    {c(B, '└─────────────────────────────┬─────────────────────────────────┘')}
                                  ▼
    {c(B, '┌─ LAYER 5: API ────────────────────────────────────────────────┐')}
    {c(B, '│')}  /lookup /search /ask  /factors /topics  /sources /authority {c(B, '│')}
    {c(B, '└───────────────────────────────────────────────────────────────┘')}
    """
    print(diagram)

    # ===================================================================
    header("FIELDS — EVERY KEY, ITS TYPE, AND ITS POPULATION", GN)
    # ===================================================================

    # Inspect ALL keys present across records
    all_keys: set[str] = set()
    for m in metas:
        all_keys.update((m or {}).keys())

    # Group keys: core (whitelisted), factor flags, anything else
    factor_keys = sorted(k for k in all_keys if k.startswith("factor_"))
    core_keys_priority = [
        "id", "citation", "state_code", "jurisdiction", "jurisdiction_norm",
        "code", "section", "title",
        "legal_topic", "topic_confidence",
        "factors_csv", "document_type", "authority_source",
        "pi_relevant", "confidence",
        "source_url",
    ]
    other_keys = sorted(k for k in all_keys
                        if k not in core_keys_priority and not k.startswith("factor_"))

    print(c(B, "  ── core fields (every record carries these) ──"))
    fmt_header = f"  {'field':<24}{'type':<14}{'fill':>5}   example"
    print()
    print(c(B, fmt_header))
    print(c(GREY, "  " + "─" * 80))

    def render_field(key: str, indent: str = "  ", color_label: str = "") -> None:
        types: Counter = Counter()
        nonempty = 0
        sample = None
        for m in metas:
            v = (m or {}).get(key)
            if v is None or v == "":
                continue
            nonempty += 1
            types[py_type_name(v)] += 1
            if sample is None:
                sample = v
        type_str = " | ".join(f"{t}({n})" if len(types) > 1 else t
                              for t, n in types.most_common(3)) or "—"
        pct = (nonempty / n * 100) if n else 0
        color = GN if pct > 95 else (YL if pct > 50 else RED)
        sample_display = ""
        if sample is not None:
            s = str(sample)
            if len(s) > 40:
                s = s[:40] + "…"
            sample_display = s
        line = f"{indent}{key:<24}{type_str:<14}{c(color, f'{pct:>4.0f}%')}   {c(D, sample_display)}"
        if color_label:
            line = f"{indent}{c(color_label, key):<{24+9}}{type_str:<14}{c(color, f'{pct:>4.0f}%')}   {c(D, sample_display)}"
        print(line)

    for k in core_keys_priority:
        if k in all_keys:
            render_field(k)

    if other_keys:
        print()
        print(c(B + GREY, "  ── other metadata keys ──"))
        for k in other_keys:
            render_field(k, color_label=GREY)

    if factor_keys:
        print()
        print(c(B, f"  ── factor flags ({len(factor_keys)} bool keys, used by Chroma where-filter) ──"))
        flag_examples = factor_keys[:6]
        for k in flag_examples:
            render_field(k, color_label=BL)
        if len(factor_keys) > 6:
            print(c(GREY, f"  …and {len(factor_keys) - 6} more (one per raw contributing factor seen in CSVs)"))

    # ===================================================================
    header("VALUE DISTRIBUTIONS — what the data actually contains", YL)
    # ===================================================================

    # By state
    sub("Records per state_code", BL)
    state_counts = Counter((m or {}).get("state_code") for m in metas)
    max_n = max(state_counts.values()) if state_counts else 1
    for st, cnt in sorted(state_counts.items(), key=lambda x: -x[1]):
        print(f"  {c(B, str(st)):<8s}  {cnt:>4d}  {bar(cnt, max_n)}  {c(D, f'{cnt/n:.0%}')}")

    # By jurisdiction
    sub("Records per jurisdiction (normalized)", BL)
    jur_counts = Counter((m or {}).get("jurisdiction_norm") or (m or {}).get("jurisdiction")
                          for m in metas)
    max_n = max(jur_counts.values()) if jur_counts else 1
    for j, cnt in sorted(jur_counts.items(), key=lambda x: -x[1]):
        print(f"  {c(B, str(j)):<22s}  {cnt:>4d}  {bar(cnt, max_n)}")

    # By document_type
    sub("Records per document_type (ready for case_law / regulation expansion)", BL)
    dt_counts = Counter((m or {}).get("document_type") for m in metas)
    for d, cnt in sorted(dt_counts.items(), key=lambda x: -x[1]):
        print(f"  {c(B, str(d)):<22s}  {cnt:>4d}  {bar(cnt, n)}")

    # By authority_source
    sub("Records per authority_source", BL)
    auth_counts = Counter((m or {}).get("authority_source") for m in metas)
    for a, cnt in sorted(auth_counts.items(), key=lambda x: -x[1]):
        label = a if a else c(GREY, "(none)")
        print(f"  {label:<22s}  {cnt:>4d}  {bar(cnt, n)}")

    # ===================================================================
    header("LEGAL TOPICS — the normalized abstraction layer", MG)
    # ===================================================================

    topic_counts = Counter((m or {}).get("legal_topic") for m in metas)
    print(f"  {c(B, 'Defined topics:')}    {len(LEGAL_TOPICS)}")
    print(f"  {c(B, 'Topics in use:')}     {len([t for t in topic_counts if t])}")
    print(f"  {c(B, 'Records w/ topic:')}  {sum(c for k, c in topic_counts.items() if k)}/{n}")
    print()
    print(c(B, "  topic distribution:"))
    max_n = max(topic_counts.values()) if topic_counts else 1
    for t, cnt in sorted(topic_counts.items(), key=lambda x: -x[1]):
        if not t:
            continue
        print(f"  {t:<40s}  {cnt:>4d}  {bar(cnt, max_n)}")

    # Confidence histogram
    sub("topic_confidence distribution", BL)
    buckets = Counter()
    for m in metas:
        conf = (m or {}).get("topic_confidence")
        if conf is None:
            buckets["null"] += 1
        elif conf >= 0.9:
            buckets["≥ 0.90"] += 1
        elif conf >= 0.7:
            buckets["0.70 – 0.89"] += 1
        elif conf >= 0.5:
            buckets["0.50 – 0.69"] += 1
        else:
            buckets["< 0.50"] += 1
    for label in ("≥ 0.90", "0.70 – 0.89", "0.50 – 0.69", "< 0.50", "null"):
        cnt = buckets.get(label, 0)
        if cnt == 0:
            continue
        color = GN if "≥" in label or "0.70" in label else (YL if "0.50" in label else RED)
        print(f"  {c(color, label):<24s}  {cnt:>4d}  {bar(cnt, n)}")

    # ===================================================================
    header("RAW FACTORS  →  NORMALIZED TOPICS  (the abstraction at work)", CY)
    # ===================================================================

    print(f"  {c(B, 'Raw factor labels in data:')}     ", end="")
    raw_factors = Counter()
    for m in metas:
        for k, v in (m or {}).items():
            if k.startswith("factor_") and v is True:
                raw_factors[k[len("factor_"):]] += 1
    print(c(YL + B, str(len(raw_factors))) + c(D, "  (messy, varies by state)"))
    print(f"  {c(B, 'Canonical topics in schema:')}    " + c(GN + B, str(len(LEGAL_TOPICS))) + c(D, "  (normalized abstraction)"))
    print()

    # raw -> topic map (which raw factor most often maps to which topic)
    raw_to_topic: dict[str, Counter] = defaultdict(Counter)
    for m in metas:
        topic = (m or {}).get("legal_topic")
        if not topic:
            continue
        for k, v in m.items():
            if k.startswith("factor_") and v is True:
                raw_to_topic[k[len("factor_"):]][topic] += 1

    print(c(B, "  Mapping examples (raw factor → most-common normalized topic):"))
    print()
    rows = sorted(raw_to_topic.items(), key=lambda kv: -sum(kv[1].values()))
    for raw, topic_counter in rows[:14]:
        topic, cnt = topic_counter.most_common(1)[0]
        total = sum(topic_counter.values())
        print(f"  {c(YL, raw[:40]):<48}  {c(D, '→')}  {c(GN, topic)}  {c(D, f'({cnt}/{total})')}")
    if len(rows) > 14:
        print(c(GREY, f"  …and {len(rows) - 14} more raw labels"))

    # ===================================================================
    header("AUTHORITATIVE-SOURCE WIKI", YL)
    # ===================================================================

    if not HAS_WIKI:
        print(c(YL, "  wiki/ not loadable — skipping"))
    else:
        sources = authority_wiki.load_sources()
        amap = authority_wiki.load_authority_map()
        kv("Sources catalogued", c(B + YL, str(len(sources))))
        kv("Source kinds",       ", ".join(authority_wiki.kinds()))
        kv("Jurisdictions",      ", ".join(authority_wiki.jurisdictions()))
        kv("Need-routes",        c(B, str(len(amap['routes']))))
        kv("Topic-routes",       c(B, str(len(amap['topic_routes']))))

        sub("Sources by kind", BL)
        kind_counts = Counter(s.get("kind") for s in sources)
        max_n = max(kind_counts.values()) if kind_counts else 1
        for k, cnt in sorted(kind_counts.items(), key=lambda x: -x[1]):
            print(f"  {c(B, k):<24s}  {cnt:>3d}  {bar(cnt, max_n)}")

    # ===================================================================
    header("CHROMA WHERE-CLAUSE TRICKS  (how filters actually work)", GREY)
    # ===================================================================

    explanations = [
        ("state_code",         "exact match",  '{"state_code": "CA"}'),
        ("legal_topic",        "exact match",  '{"legal_topic": "DUI-related behavior"}'),
        ("jurisdiction_norm",  "exact match",  '{"jurisdiction_norm": "California"}'),
        ("factor_<NAME>",      "bool flag",    '{"factor_DUI/DWI": true}'),
        ("topic_confidence",   "comparator",   '{"topic_confidence": {"$gte": 0.9}}'),
        ("multiple",           "AND combine",  '{"$and": [{"state_code":"CA"},{"legal_topic":"hit and run"}]}'),
    ]
    hdr = f"  {'filter type':<22}  {'mechanism':<14}  example where-clause"
    print(c(B, hdr))
    print(c(GREY, "  " + "─" * 80))
    for name, mech, ex in explanations:
        print(f"  {c(YL, name):<31s}  {mech:<14s}  {c(D, ex)}")

    # ===================================================================
    header("ENDPOINTS  (what the API exposes)", GN)
    # ===================================================================
    eps = [
        ("GET",  "/healthz",    "DB up + record count"),
        ("GET",  "/factors",    "List the 17 raw contributing-factor categories"),
        ("GET",  "/topics",     f"List the {len(LEGAL_TOPICS)} normalized legal topics"),
        ("GET",  "/lookup",     "Exact citation lookup → single record"),
        ("GET",  "/search",     "Semantic search + filters (state, factor, legal_topic, jurisdiction, document_type, authority_source, min_topic_confidence, pi_only)"),
        ("POST", "/ask",        "Same as /search but JSON body — for chat agents"),
        ("GET",  "/sources",    "Authoritative-source catalog (filter by state, kind)"),
        ("GET",  "/authority",  "Authority routing — `which sources for what` (legal_topic OR need)"),
    ]
    print(c(B, f"  {'method':<7}{'path':<14}  description"))
    print(c(GREY, "  " + "─" * 80))
    for m_, path, desc in eps:
        method_color = BL if m_ == "GET" else MG
        print(f"  {c(method_color + B, m_):<16s}{c(B, path):<23s}  {desc}")

    # ===================================================================
    header("ONE-LINE TL;DR", CY)
    # ===================================================================
    print(f"""
  {c(B, str(n))} statutes across {c(B, str(len(state_counts)))} jurisdictions, every record carrying
  {c(B, str(len(core_keys_priority)))} core fields + {c(B, str(len(factor_keys)))} factor flags + a {c(B, '1024-dim')} Voyage
  embedding. Three semantic layers (raw factor → normalized topic →
  authority source), {c(B, str(len(LEGAL_TOPICS)))} topics in use, retrievable via 8 API
  endpoints with structured filtering, vector similarity, or both.
""")


if __name__ == "__main__":
    main()
