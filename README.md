# Specter

> Legal research agent for personal injury attorneys.
> EvenUp × OpenClaw Hackathon — May 9, 2026.

## What it is

A queryable database of US motor vehicle statutes, tagged with personal-injury-relevant contributing factors, with semantic + filtered retrieval. The Harvester layer.

WhatsApp-facing OpenClaw agent talks to a FastAPI service backed by Chroma + Voyage `voyage-law-2` embeddings.

## Specter's persona

- `IDENTITY.md` — name, vibe, emoji.
- `SOUL.md` — voice, tone, behavior, hard rules (no fabrication, source URLs required, etc.).

Loaded by OpenClaw at the start of every agent turn. Edit them to tune Specter's behavior.

## Reference materials

- `sources/` — **external truths**: hackathon brief, scoring rubric, released eval CSV. Treat as canon, do not modify, do not put product/persona files here.
- `IDENTITY.md` / `SOUL.md` — **internal truths**: who Specter is and how she talks.
- `data/eval-ca-vehicle-code.csv` — working copy of the released eval set used by the harvester/eval pipeline.
- `data/pi_playbook.yaml` — hand-curated PI doctrine notes per contributing-factor (NPS analysis, common defenses, evidence checklist, PI angle). Used by the brief formatter to turn a Wikipedia-style citation into a PI-lawyer-grade brief block.

## Architecture

```
WhatsApp ─► OpenClaw agent ─► FastAPI (this repo) ─► Chroma (Voyage embeddings)
                                                  └─► Anthropic (query understanding, optional rerank)
```

## Layout

```
specter/
├── harvester/          # Scrapers per jurisdiction → data/raw/*.json
│   └── scrapers/
│       ├── ca.py       # California (leginfo or LII)
│       ├── ny.py
│       ├── tx.py
│       ├── fl.py
│       └── il.py
├── tagger/             # Claude → 17-category contributing-factor labels
│   ├── prompt.py
│   └── tag.py          # batch tagger: data/raw/*.json → data/tagged/*.json
├── api/                # FastAPI: /lookup, /search, /ask
│   ├── main.py
│   ├── chroma_store.py
│   └── voyage_embed.py
├── evals/              # Run released CSV against the API
│   └── run_eval.py
├── data/
│   ├── raw/            # untagged statutes (per-state JSON)
│   ├── tagged/         # tagged statutes ready for Chroma
│   └── eval-ca-vehicle-code.csv  # released set (the rosetta stone)
├── scripts/
│   └── load_chroma.py  # tagged JSON → Chroma collection
├── Makefile
├── requirements.txt
└── .env.example
```

## Schema (a record)

```json
{
  "id": "ca-vc-23152-a",
  "jurisdiction": "California",
  "state_code": "CA",
  "code": "Cal. Veh. Code",
  "section": "23152(a)",
  "citation": "Cal. Veh. Code § 23152(a)",
  "title": "Driving under the influence of alcohol",
  "text": "It is unlawful for any person who is under the influence...",
  "hierarchy_path": ["Vehicle Code", "Division 11", "Chapter 12", "Article 2"],
  "effective_date": "2024-01-01",
  "source_url": "https://leginfo.legislature.ca.gov/...",
  "contributing_factors": ["DUI/DWI"],
  "pi_relevant": true,
  "confidence": 0.98
}
```

## The 17 contributing-factor categories

From the released CSV:

DUI/DWI · Driving Too Fast For Conditions · Failure to Maintain Lane · Failure to Obey Traffic Control Device · Failure to Use/Activate Horn · Failure to Yield at a Yield Sign · Failure to Yield the Right-of-Way · Fleeing a Police Officer · Fleeing the Scene of a Collision · Following Too Closely · Improper Lane of Travel · Improper Passing · Improper Starting · Improper Stopping · Improper Turning · Reckless Driving · Using a Wireless Telephone/Texting While Driving

## Quickstart

```bash
make install          # pip install
cp .env.example .env  # add VOYAGE_API_KEY, ANTHROPIC_API_KEY
make ingest           # run all scrapers
make tag              # tag every raw statute
make load             # push tagged JSON into Chroma
make serve            # FastAPI on :8000
make eval             # run the released CSV against the API
```

## API contract (lock this in first 30 min)

```
GET  /healthz
GET  /lookup?citation=Cal.+Veh.+Code+§+23152(a)
GET  /search?q=driving+drunk&state=CA&factor=DUI%2FDWI&k=10
POST /ask     { "question": "What CA statutes cover DUI?" }
```

All responses include `source_url` on every record. Per ground rules, no source URL = doesn't count.

## Team split

| Person | Track |
|---|---|
| 1 | CA full + 1 state ingest |
| 2 | 3 more states ingest |
| 3 | Tagging pipeline |
| 4 | Chroma + FastAPI + Voyage |
| 5 | OpenClaw / WhatsApp wiring + prompts |
| 6 | Eval + demo |
