# Specter

> **A senior PI defense attorney in your text messages.**
> EvenUp × OpenClaw Hackathon — May 9, 2026.

Specter is a Harvey-Specter-voiced WhatsApp agent for personal-injury work. A paralegal texts a citation, fact pattern, or case description — Specter pulls statutes from a multi-state, semantically-indexed database, surfaces appellate cases that interpret them, drafts the negligence-per-se framing, lists common defenses + evidence to gather, and finds damages comparables. Every section number she cites is sourced; nothing is fabricated, nothing is paraphrased from training memory.

Under the hood: 384 tagged statutes across 6 states, a curated wiki of authoritative sources, a token-rate-limited Voyage `voyage-law-2` vector index, and an Organizer endpoint that turns a fact pattern into a structured paralegal workspace. The PI playbook + brief formatter is hand-curated, not LLM-generated.

---

## ⚡ At a glance

| Layer | What | Numbers |
|---|---|---|
| **Coverage** | Vehicle / traffic statutes across U.S. jurisdictions | **384 records · 6 states** (CA, TX, FL, PA, IL, OH) |
| **Classification** | Raw `contributing_factor` from each state's CSV | 17-category schema + per-state extras |
| **Abstraction** | Normalized `legal_topic` (Claude-enriched) | **21 topics · 19 in active use** · 73% records ≥ 0.9 confidence |
| **Embeddings** | Voyage `voyage-law-2` over the statute text | 1024-dim, unit-normalized, cosine search |
| **Storage** | Local Chroma persistent collection | `./.chroma/` (~3.4 MB) |
| **Wiki** | Curated authoritative-source registry | **22 sources · 7 kinds · 18 routes** |
| **API** | FastAPI on `:8000` | 8 endpoints, JSON in / out |
| **Released-set eval** | Citation lookup against the released CA CSV | **100 %** on the 41-row released set |

---

## 🧠 Architecture

```
                                                              ┌─► Voyage law-2 (1024-dim legal embeddings)
                                                              ├─► Chroma (cosine + factor/topic where-clauses)
                                                              ├─► wiki/ (authority routing — "which sources for what")
WhatsApp ─► OpenClaw agent ─► 5 skills ─► FastAPI (this repo) ─┤
          (Harvey persona)                                    ├─► CourtListener API (appellate case retrieval)
                                                              ├─► Anthropic Claude (factor + topic enrichment, gap-detect)
                                                              └─► authoritative `.gov` legislatures (live verify fallback)
```

The 5 OpenClaw skills are: `harvester_query` (statute lookup) · `caselaw_query` (CourtListener) · `pi_brief_format` (Harvey-voiced lawyer brief) · `citation_format` (normalize messy citation strings) · `web_fallback` (verified live-fetch when the database misses).

The Organizer extension (`api/organizer.py` + `data/comparables.csv`) layers paralegal-grade workflows on top: case-aware statute pull, sortable damages comparables, Claude-driven coverage-gap detection. Surfaced via `/comparables` and `/organize`.

For a live, terminal-friendly walkthrough:

```bash
make visualize-entire-architecture-project   # full system + user data flow
make schema                                  # every field, type, distribution
make chroma-viz                              # vector store deep dive
make mermaid                                 # write Mermaid diagrams to diagrams/
```

Or render any of `diagrams/*.mmd` at <https://mermaid.live>.

---

## 🚀 Quickstart

```bash
make install                  # pip install -r requirements.txt
cp .env.example .env          # then fill in VOYAGE_API_KEY + ANTHROPIC_API_KEY
make seed                     # CSV → data/raw/<state>-eval.json
make tag                      # Claude factor classifier → data/tagged/
make load                     # tagged JSON → Chroma w/ Voyage embeddings (incremental)
PYTHONPATH=. .venv/bin/python -m tagger.enrich    # adds legal_topic / topic_confidence / etc.
make serve                    # FastAPI on http://localhost:8000
```

Verify:

```bash
curl http://localhost:8000/healthz
# {"ok": true, "collection": "specter_statutes", "count": 384}
```

---

## 🎬 Demos

```bash
make demo                    # structured tour: cross-state, factor + topic filters, /ask
make demo-realistic          # messy human-language queries
make demo-big-ass-query      # full Anaheim phantom-vehicle case workup, end-to-end
make browse                  # curses TUI to scroll every record (lawyer/engineer toggle)
make sources                 # the authoritative-source catalog
make authority               # the "which sources for what" wiki, demoed
```

---

## 📚 Reference materials & persona

- `sources/` — **external truths**: hackathon brief, scoring rubric, released eval CSV. Canon. Don't modify.
- `wiki/sources.yaml` — catalog of 22 trusted sources across 7 kinds (statute / case-law / bar / court / federal / state).
- `wiki/authority_map.yaml` — the routing layer: *"for question X, use source Y."*
- `IDENTITY.md` / `SOUL.md` — Specter's persona (loaded by OpenClaw at every turn). Hard rules: no fabrication, every citation carries a source URL, no internal jargon (`Harvester`, `skill`, `Chroma`, etc.) leaks to users.
- `data/pi_playbook.yaml` — hand-curated PI-doctrine notes per factor (NPS analysis, common defenses, evidence checklist). Used by the brief formatter.
- `data/factor_synonyms.yaml` — maps non-canonical state factor labels to the canonical 17-cat schema.
- `data/comparables.csv` — settlement / verdict comparables surfaced by the Organizer (`/comparables`).

---

## 🗂 Repo layout

```
specter/
├── harvester/                       # Schema + scraper stubs
│   ├── schema.py                    # StatuteRecord (Pydantic) + 17 factors
│   └── scrapers/{ca,tx,fl,pa,il,oh,…}.py
├── tagger/                          # LLM enrichment
│   ├── prompt.py                    # 17-cat classifier prompt
│   ├── tag.py                       # batch tagger: data/raw/*.json → data/tagged/*.json
│   └── enrich.py                    # adds legal_topic / topic_confidence / jurisdiction_norm
│                                    # / document_type / authority_source IN-PLACE
│                                    # (preserves embeddings via collection.update())
├── api/                             # FastAPI service surface
│   ├── main.py                      # /healthz /factors /topics /lookup /search /ask
│   │                                # /sources /authority /comparables /organize
│   ├── chroma_store.py              # Chroma wrapper + factor-flag filtering trick
│   ├── voyage_embed.py              # Lazy Voyage client + RPM token bucket + LRU cache
│   ├── pi_brief.py                  # PI-lawyer brief formatter
│   └── organizer.py                 # Paralegal workspace: comparables filter, gap detect
├── wiki/                            # Authoritative-source wiki (the bonus deliverable)
│   ├── sources.yaml                 # 22 sources, 7 kinds, 6 jurisdictions
│   ├── authority_map.yaml           # 18 need-routes + 5 topic-routes
│   └── __init__.py                  # loaders + route_for_need / route_for_topic
├── scripts/                         # Operator + demo CLI
│   ├── seed_from_eval.py            # CSV → data/raw
│   ├── load_chroma.py               # incremental Voyage embed → Chroma
│   ├── pretty.py                    # ANSI-rendered API client
│   ├── browse.py                    # curses TUI
│   ├── schema.py                    # live schema introspector
│   ├── architecture.py              # full architecture visualizer
│   ├── chroma_viz.py                # vector-store deep dive
│   ├── mermaid.py                   # Mermaid diagram generator
│   └── case_demo.sh                 # Anaheim phantom-vehicle showpiece
├── evals/run_eval.py                # citation lookup + factor retrieval@k against released CSV
├── data/
│   ├── eval-{ca,tx,fl,pa,il,oh}-vehicle-code.csv
│   ├── raw/<state>-eval.json
│   ├── tagged/<state>-eval.json
│   ├── pi_playbook.yaml
│   └── factor_synonyms.yaml
├── openclaw/skills/                 # Skills loaded by the WhatsApp agent
│   ├── harvester_query/             # statute lookup / search / ask via the FastAPI
│   ├── caselaw_query/               # appellate cases citing a statute (CourtListener)
│   ├── pi_brief_format/             # render a Harvey-voiced lawyer brief
│   ├── citation_format/             # normalize messy citation strings
│   └── web_fallback/                # verified live-fetch when the database misses
├── diagrams/                        # Generated by `make mermaid`
├── Makefile                         # Every operator + demo + viz target
├── requirements.txt
└── .env.example
```

---

## 🧾 Schema (a record in Chroma)

```json
{
  "id": "ca-vc-23152-a",
  "citation": "Cal. Veh. Code § 23152(a)",
  "state_code": "CA",
  "jurisdiction": "California",
  "jurisdiction_norm": "California",
  "code": "Cal. Veh. Code",
  "section": "23152(a)",
  "title": "Driving under the influence of alcohol",
  "text": "It is unlawful for a person who is under the influence...",
  "source_url": "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=VEH&sectionNum=23152.",
  "document_type": "statute",
  "authority_source": "state_legislature",

  "factors_csv": "DUI/DWI",
  "factor_DUI/DWI": true,            // bool flag, used by Chroma where-clauses
  "pi_relevant": true,
  "confidence": 1.0,                  // ground-truth label confidence

  "legal_topic": "DUI-related behavior",
  "topic_confidence": 0.99,

  // plus a 1024-dim Voyage law-2 embedding (not in metadata, lives in vector store)
}
```

For the full ER diagram see `diagrams/erd.mmd` (paste at <https://mermaid.live>).

---

## 🌐 API contract

| Method | Path | What it does |
|---|---|---|
| GET | `/healthz` | Health + record count |
| GET | `/factors` | The 17 raw contributing-factor categories |
| GET | `/topics` | The 21 normalized legal topics (the abstraction layer) |
| GET | `/lookup?citation=…` | Exact citation → single record |
| GET | `/search?q=…&state=…&factor=…&legal_topic=…&jurisdiction=…&document_type=…&authority_source=…&min_topic_confidence=…&pi_only=…&k=…` | Vector search + structured filters |
| POST | `/ask` | Same engine as `/search`, JSON body — ergonomic for chat agents |
| GET | `/sources?state=…&kind=…` | Browse the curated source catalog |
| GET | `/authority?legal_topic=…&state=…` *or* `?need=…&jurisdiction=…` | Authority routing — *"which sources are authoritative for what."* |
| GET | `/comparables?state=…&injury=…&defendant=…&min_amount=…&max_amount=…&year_from=…&year_to=…&sort=…` | Sortable damages comparables (Organizer) |
| POST | `/organize` | Full Organizer pass on a case description: applicable statutes + comparables + gap detection |

All responses include `source_url` on every record. Per hackathon ground rules, no source URL = doesn't count.

---

## 🏷 The 17 contributing-factor categories (raw layer)

DUI/DWI · Driving Too Fast For Conditions · Failure to Maintain Lane · Failure to Obey Traffic Control Device · Failure to Use/Activate Horn · Failure to Yield at a Yield Sign · Failure to Yield the Right-of-Way · Fleeing a Police Officer · Fleeing the Scene of a Collision · Following Too Closely · Improper Lane of Travel · Improper Passing · Improper Starting · Improper Stopping · Improper Turning · Reckless Driving · Using a Wireless Telephone/Texting While Driving

## 🧠 The 21 normalized legal topics (abstraction layer)

`DUI-related behavior` · `speeding` · `distracted driving` · `failure to yield` · `reckless driving` · `improper lane usage` · `improper turning` · `improper passing` · `improper stopping or starting` · `following too closely` · `fleeing or evading` · `hit and run` · `traffic control device violation` · `hazardous driving conditions` · `vehicle equipment violation` · `right-of-way violation` · `racing or exhibition` · `license or registration violation` · `school zone or bus violation` · `pedestrian or bicycle protection` · `general traffic violation`

---

## 🛠 Make targets

| Operator | Visualization | Demos |
|---|---|---|
| `make install` | `make schema` | `make demo` |
| `make seed` | `make visualize-entire-architecture-project` | `make demo-realistic` |
| `make tag` | `make chroma-viz` | `make demo-big-ass-query` |
| `make load` | `make mermaid` | `make sources` |
| `make serve` | `make browse` | `make authority` |
| `make eval` | | |
| `make clean` | | |

`PY` defaults to `.venv/bin/python` if it exists, otherwise `python3`.

---

## ⚙️ External services

| Service | Used for | Env |
|---|---|---|
| Voyage AI (`voyage-law-2`) | 1024-dim legal embeddings | `VOYAGE_API_KEY` |
| Anthropic (`claude-haiku-4-5`) | Factor tagging + topic enrichment + Organizer gap detect | `ANTHROPIC_API_KEY` |
| CourtListener (Free Law Project) | Appellate case retrieval (`caselaw_query` skill) | `COURTLISTENER_API_KEY` (free tier 5,000 q/h) |
| Chroma (PersistentClient) | Local vector DB | — |
| OpenClaw (separate process) | WhatsApp-facing chat surface | — |

`api/voyage_embed.py` enforces a token-bucket RPM limit (`VOYAGE_RPM`, default 3 for the free tier; bump to 300 with a card on file). It also LRU-caches every embedding, so demo retries are free.

---

## 🧪 Hackathon scoring posture

- **Harvester (50 pts)** — 384 records across 6 states (CA, TX, FL, PA, IL, OH), normalized topic + raw factor dual-label, factor-flag filtering, hand-tuned Chroma where-clauses. ✅ floor (released CA CSV) at 100 % citation lookup.
- **Authority wiki bonus** — `/authority` endpoint backed by `wiki/sources.yaml` + `wiki/authority_map.yaml`, with topic ladders (primary statute / case law / statistics) and need-based routing.
- **Organizer extension (30 pts)** — `api/organizer.py` + `/comparables` + `/organize` deliver the rubric's paralegal workspace: case-aware statute pull, sortable damages comparables, Claude-driven coverage-gap detection. The brief formatter (`api/pi_brief.py`) renders Harvey-voiced lawyer briefs end-to-end on WhatsApp.
- **Case-law layer** — `caselaw_query` skill surfaces appellate decisions interpreting any cited statute via CourtListener. Empirically verified: TX speed-law § 545.351 returns 8 appellate cases; FL DUI § 316.193 returns 54.
- **No fabrication** — every section number Specter cites carries a source URL on the same page. Hard rules in `SOUL.md` forbid the common failure modes ("verify before filing", "approximate citation", "from memory"). When live-verify and database both miss, she refuses honestly.
- **Story (10 pts)** — `make demo-big-ass-query` is the 5-minute showpiece. The WhatsApp persona is the throughline.

---

## 📝 Notes for future you

- Every record carries a verifiable `source_url`. **No source URL = the record doesn't count** (per ground rules + SOUL.md).
- The `legal_topic` abstraction means the system can answer *"distracted driving statutes"* across all states even when each state spells the raw factor differently.
- Adding a new state is a CSV drop-in: add `data/eval-<XX>-vehicle-code.csv`, register the state in `scripts/seed_from_eval.py`, then `make seed && make tag && make load && PYTHONPATH=. .venv/bin/python -m tagger.enrich`.
- The Voyage rate limit on the free tier is the most common failure mode. If `make eval` returns 500s, add a payment method and bump `VOYAGE_RPM=300`.
