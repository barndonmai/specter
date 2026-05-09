#!/usr/bin/env python3
"""
Generate Mermaid.js diagrams of Specter's schema + architecture.

Produces several .mmd files in `diagrams/` AND prints them to stdout.
Paste any of them into:
  - https://mermaid.live  (instant browser preview)
  - GitHub markdown (works natively)
  - VS Code with the Mermaid Preview extension
  - Notion / Obsidian / etc.

Diagrams emitted:
  diagrams/erd.mmd            — full entity-relationship diagram (DB-style)
  diagrams/architecture.mmd   — system / service architecture
  diagrams/user-flow.mmd      — user data flow (WhatsApp → API → Chroma → reply)
  diagrams/pipeline.mmd       — ingestion pipeline (CSV → Chroma)
  diagrams/topic-flow.mmd     — raw factor → normalized topic mapping (live data)

Usage:
    make mermaid
    python scripts/mermaid.py [erd|architecture|user-flow|pipeline|topic-flow|all]
    python scripts/mermaid.py --print          # also dump the chosen one to stdout
"""
from __future__ import annotations
import argparse
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "diagrams"
OUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------- ERD

ERD_MMD = """\
erDiagram
    %% =========================================================
    %% Specter logical schema (Chroma-backed, but modeled here as
    %% if it were a relational store so an attorney can read it).
    %% =========================================================

    LEGAL_DOCUMENT {
        string  id              PK "stable slug, e.g. ca-vc-23152-a"
        string  citation        "Cal. Veh. Code § 23152(a)"
        string  state_code      "CA"
        string  jurisdiction_id FK
        string  code            "Cal. Veh. Code"
        string  section         "23152(a)"
        string  title
        string  text            "full statute language"
        string  source_url      "REQUIRED — points at AUTHORITY_SOURCE"
        string  document_type   "statute | case_law | regulation | guidance | dataset"
        boolean pi_relevant
        float   confidence      "0.0-1.0 — confidence on raw factor label"
        string  authority_source_id FK
        string  legal_topic_id  FK
        float   topic_confidence "0.0-1.0 — confidence on legal_topic"
        vector  embedding       "1024-dim Voyage law-2"
    }

    JURISDICTION {
        string state_code   PK "CA, TX, FL, PA, IL, OH"
        string name         "California, Texas, ..."
        string country      "US"
    }

    LEGAL_TOPIC {
        string id           PK "normalized key e.g. dui-related-behavior"
        string label        "DUI-related behavior"
        string description
    }

    CONTRIBUTING_FACTOR {
        string id           PK "raw label e.g. DUI/DWI"
        string label        "raw text from source CSV"
        boolean canonical   "true = part of the official 17-cat schema"
    }

    DOCUMENT_TOPIC_LINK {
        string id            PK
        string document_id   FK
        string topic_id      FK
        float  confidence
    }

    DOCUMENT_FACTOR_LINK {
        string id            PK
        string document_id   FK
        string factor_id     FK
    }

    AUTHORITY_SOURCE {
        string id            PK "ca-leginfo, tx-statutes-capitol, courtlistener, ..."
        string name
        string kind          "primary_statute | case_law | bar_association | court_system | federal_dataset | federal_agency | state_agency"
        string authority_tier "primary | secondary | tertiary"
        string url
        string state_code    FK
        boolean is_official
        string operator
    }

    AUTHORITY_ROUTE {
        string id              PK
        string need            "Find court opinions interpreting a statute"
        string for_jurisdiction "ANY | California | Texas | ..."
        string keywords        "[case, law, opinion, ...]"
    }

    ROUTE_SOURCE_LINK {
        string id          PK
        string route_id    FK
        string source_id   FK
        string tier        "primary | secondary"
    }

    TOPIC_AUTHORITY_ROUTE {
        string id                       PK
        string legal_topic_id           FK
        string primary_statute_state    "JSON map state_code -> source_id"
        string case_law_source_id       FK
        string statistics_source_id     FK
        string authority_note
    }

    %% --- relationships --------------------------------------------------

    JURISDICTION       ||--o{ LEGAL_DOCUMENT          : "issues"
    AUTHORITY_SOURCE   ||--o{ LEGAL_DOCUMENT          : "is the source for"
    LEGAL_TOPIC        ||--o{ LEGAL_DOCUMENT          : "categorizes (denormalized)"

    LEGAL_DOCUMENT     ||--o{ DOCUMENT_TOPIC_LINK     : "tagged with"
    LEGAL_TOPIC        ||--o{ DOCUMENT_TOPIC_LINK     : "applies to"

    LEGAL_DOCUMENT     ||--o{ DOCUMENT_FACTOR_LINK    : "raw-labeled with"
    CONTRIBUTING_FACTOR||--o{ DOCUMENT_FACTOR_LINK    : "applied to"

    JURISDICTION       ||--o{ AUTHORITY_SOURCE        : "publishes"

    AUTHORITY_ROUTE    ||--o{ ROUTE_SOURCE_LINK       : "ranks"
    AUTHORITY_SOURCE   ||--o{ ROUTE_SOURCE_LINK       : "appears in"

    LEGAL_TOPIC        ||--o| TOPIC_AUTHORITY_ROUTE   : "has authority ladder"
    AUTHORITY_SOURCE   ||--o{ TOPIC_AUTHORITY_ROUTE   : "referenced by ladder"
"""


# ---------------------------------------------------------------- ARCHITECTURE

ARCH_MMD = """\
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#1e1e2e","primaryTextColor":"#cdd6f4","lineColor":"#89b4fa"}} }%%
flowchart TB
    %% =========================================================
    %% Specter — system architecture
    %% =========================================================

    subgraph Client["👤 Client"]
        WA["WhatsApp / chat surface"]
    end

    subgraph Agent["🤖 OpenClaw agent (separate process)"]
        SOUL["SOUL.md persona"]
        Skills["openclaw/skills/<br/>• harvester-query<br/>• pi_brief_format<br/>• citation-format<br/>• web_fallback"]
    end

    subgraph SpecterAPI["🧠 Specter API (FastAPI :8000)"]
        Main["api/main.py<br/>endpoints:<br/>• /lookup<br/>• /search<br/>• /ask<br/>• /factors • /topics<br/>• /sources • /authority"]
        Voyage["api/voyage_embed.py<br/>• lazy client<br/>• RPM token-bucket<br/>• LRU cache<br/>• 429 retry"]
        Chroma["api/chroma_store.py<br/>• filter flags<br/>• cosine search<br/>• $and assembly"]
        Brief["api/pi_brief.py<br/>(attorney-style output)"]
    end

    subgraph Wiki["📚 Authority wiki (yaml)"]
        Sources["wiki/sources.yaml<br/>22 sources, 7 kinds"]
        Map["wiki/authority_map.yaml<br/>18 need-routes,<br/>5 topic-routes"]
    end

    subgraph Storage["💾 Local persistent storage"]
        ChromaDB[("Chroma DB<br/>./.chroma/<br/>384 records<br/>1024-dim cosine")]
        Raw[("data/raw/*.json")]
        Tagged[("data/tagged/*.json")]
        CSVs[("data/eval-*.csv")]
    end

    subgraph External["☁️ External services"]
        VoyageAPI["Voyage AI<br/>voyage-law-2<br/>(embeddings)"]
        Anthropic["Anthropic<br/>claude-haiku-4-5<br/>(tagging + enrichment)"]
    end

    subgraph Pipeline["⚙️ Build pipeline (offline)"]
        Seed["scripts/seed_from_eval.py"]
        Tag["tagger/tag.py"]
        Load["scripts/load_chroma.py"]
        Enrich["tagger/enrich.py"]
    end

    WA --> Skills
    Skills --> Main
    Main --> Voyage --> VoyageAPI
    Main --> Chroma --> ChromaDB
    Main --> Brief
    Main --> Sources
    Main --> Map

    CSVs --> Seed --> Raw --> Tag --> Tagged
    Tag -.uses.-> Anthropic
    Tagged --> Load --> ChromaDB
    Load -.uses.-> VoyageAPI
    Enrich --> ChromaDB
    Enrich -.uses.-> Anthropic

    classDef external fill:#fff5e1,stroke:#cba6f7,color:#000
    classDef storage  fill:#e8f5e9,stroke:#a6e3a1,color:#000
    classDef api      fill:#e3f2fd,stroke:#89b4fa,color:#000
    classDef wiki     fill:#fff9c4,stroke:#f9e2af,color:#000

    class VoyageAPI,Anthropic external
    class ChromaDB,Raw,Tagged,CSVs storage
    class Main,Voyage,Chroma,Brief api
    class Sources,Map wiki
"""


# ---------------------------------------------------------------- USER FLOW

USER_FLOW_MMD = """\
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#1e1e2e","lineColor":"#fab387"}} }%%
sequenceDiagram
    autonumber
    actor U as 👤 Paralegal / Attorney
    participant WA as WhatsApp
    participant OC as OpenClaw agent
    participant API as Specter API (FastAPI)
    participant V as Voyage law-2
    participant CH as Chroma vector DB
    participant W as Authority wiki

    U->>WA: "client got rear-ended by drunk driver in CA"
    WA->>OC: deliver message
    OC->>OC: pick skill (harvester-query)
    OC->>API: POST /ask {question, state:"CA"}
    API->>V: embed(query)  [RPM-limited, cached]
    V-->>API: 1024-dim vector
    API->>CH: query(vec, where={state:"CA"})
    CH-->>API: top-K records (citation, text, source_url, legal_topic, score)

    Note over API,W: optional: route to authoritative sources
    API->>W: route_for_topic("DUI-related behavior", state="CA")
    W-->>API: primary_statute + case_law + statistics + authority_note

    API-->>OC: results (statutes + authority ladder)
    OC->>OC: compose reply (every citation MUST carry a source URL)
    OC-->>WA: "Three CA statutes apply: § 23152, § 23153, § 23152(c).<br/>Source: leginfo.legislature.ca.gov.<br/>Case-law workup → CourtListener."
    WA-->>U: rendered message

    Note over U,WA: round-trip ~300-800ms with Voyage card,<br/>longer on free 3 RPM tier
"""


# ---------------------------------------------------------------- PIPELINE

PIPELINE_MMD = """\
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#1e1e2e","lineColor":"#a6e3a1"}} }%%
flowchart LR
    %% =========================================================
    %% Build pipeline — CSV in, Chroma out
    %% =========================================================

    CSV[("data/eval-*-<br/>vehicle-code.csv<br/>per state")]:::input
    Raw[("data/raw/<br/>*-eval.json")]:::stage
    Tagged[("data/tagged/<br/>*-eval.json")]:::stage
    Vec[("Chroma<br/>./.chroma/<br/>384 records,<br/>1024-dim")]:::vec

    Seed[scripts/seed_from_eval.py]:::script
    Tag[tagger/tag.py]:::script
    Load[scripts/load_chroma.py]:::script
    Enrich[tagger/enrich.py]:::script

    Voyage[("Voyage law-2<br/>embed()")]:::external
    Claude[("Claude Haiku<br/>classify()")]:::external

    CSV -- "make seed" --> Seed --> Raw
    Raw -- "make tag" --> Tag --> Tagged
    Tag -.uses.-> Claude
    Tagged -- "make load<br/>(incremental)" --> Load --> Vec
    Load -.embeds via.-> Voyage
    Vec -- "make enrich<br/>(in-place metadata)" --> Enrich
    Enrich -.classifies via.-> Claude
    Enrich -.update().-> Vec

    classDef input    fill:#fff5e1,stroke:#cba6f7,color:#000
    classDef stage    fill:#e8f5e9,stroke:#a6e3a1,color:#000
    classDef vec      fill:#e3f2fd,stroke:#89b4fa,color:#000
    classDef script   fill:#1e1e2e,stroke:#cba6f7,color:#cdd6f4
    classDef external fill:#fff9c4,stroke:#f9e2af,color:#000
"""


# ---------------------------------------------------------------- TOPIC FLOW (LIVE)

def topic_flow_mmd() -> str:
    """
    Live mapping of raw factor labels → normalized legal_topic, generated
    from the actual Chroma DB. Caps at the most-common 25 mappings.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from api import chroma_store
        coll = chroma_store.get_collection()
        res = coll.get(include=["metadatas"])
        metas = res["metadatas"]
    except Exception as e:
        return f"%% could not load chroma: {e}\nflowchart LR\n    A[chroma not available]"

    raw_to_topic: dict[str, Counter] = defaultdict(Counter)
    for m in metas:
        topic = (m or {}).get("legal_topic")
        if not topic:
            continue
        for k, v in m.items():
            if k.startswith("factor_") and v is True:
                raw_to_topic[k[len("factor_"):]][topic] += 1

    # Total per raw label, descending
    rows = sorted(raw_to_topic.items(), key=lambda kv: -sum(kv[1].values()))[:25]

    def slug(s: str) -> str:
        return ("R_" + s).replace(" ", "_").replace("/", "_").replace("-", "_") \
                          .replace("(", "").replace(")", "").replace(".", "_")

    # Collect unique topics
    topics = sorted({t for _, ctr in rows for t in ctr})
    topic_id = {t: f"T_{i}" for i, t in enumerate(topics)}

    lines = [
        "%%{init: {\"theme\":\"base\",\"themeVariables\":{\"primaryColor\":\"#1e1e2e\",\"lineColor\":\"#f9e2af\"}} }%%",
        "flowchart LR",
        "    %% Live raw-factor → normalized-topic mapping (top 25 raw labels)",
        "",
    ]
    for raw, ctr in rows:
        n = sum(ctr.values())
        lines.append(f'    {slug(raw)}["{raw}<br/>({n} records)"]:::raw')
    lines.append("")
    for t, tid in topic_id.items():
        n = sum(ctr.get(t, 0) for _, ctr in rows)
        lines.append(f'    {tid}(("{t}<br/>{n}")):::topic')
    lines.append("")
    for raw, ctr in rows:
        for t, n in ctr.most_common():
            lines.append(f"    {slug(raw)} -- {n} --> {topic_id[t]}")
    lines.extend([
        "",
        "    classDef raw   fill:#fff5e1,stroke:#cba6f7,color:#000",
        "    classDef topic fill:#e3f2fd,stroke:#89b4fa,color:#000",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------- MAIN

DIAGRAMS = {
    "erd":          ("diagrams/erd.mmd",          lambda: ERD_MMD,        "Entity-relationship diagram (DB-style)"),
    "architecture": ("diagrams/architecture.mmd", lambda: ARCH_MMD,       "System / service architecture"),
    "user-flow":    ("diagrams/user-flow.mmd",    lambda: USER_FLOW_MMD,  "User request sequence (WhatsApp → reply)"),
    "pipeline":     ("diagrams/pipeline.mmd",     lambda: PIPELINE_MMD,   "Ingestion pipeline (CSV → Chroma)"),
    "topic-flow":   ("diagrams/topic-flow.mmd",   topic_flow_mmd,         "LIVE raw-factor → topic mapping"),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", nargs="?", default="all",
                    choices=list(DIAGRAMS.keys()) + ["all"])
    ap.add_argument("--print", action="store_true",
                    help="Also print the chosen diagram(s) to stdout")
    args = ap.parse_args()

    targets = list(DIAGRAMS.keys()) if args.which == "all" else [args.which]

    print()
    print("Generating Mermaid diagrams …")
    print()
    written: list[Path] = []
    for key in targets:
        path_str, fn, desc = DIAGRAMS[key]
        path = ROOT / path_str
        content = fn()
        path.write_text(content)
        written.append(path)
        size_kb = len(content) / 1024
        print(f"  ✓  {path.relative_to(ROOT)}  ({size_kb:.1f} KB)  — {desc}")

    print()
    print("Open any of these in:")
    print("  • https://mermaid.live   (paste contents)")
    print("  • GitHub README          (wrap in ```mermaid ... ```)")
    print("  • VS Code (with the Mermaid Preview extension)")
    print()
    print("Or one-shot copy to clipboard (Linux):")
    for p in written:
        print(f"  cat {p.relative_to(ROOT)} | xclip -selection clipboard")

    if args.__dict__["print"]:
        for p in written:
            print()
            print(f"━━━━━━━━━ {p.relative_to(ROOT)} ━━━━━━━━━")
            print(p.read_text())


if __name__ == "__main__":
    main()
