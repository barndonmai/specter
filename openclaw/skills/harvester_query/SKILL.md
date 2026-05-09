---
name: harvester-query
description: Use whenever the user asks about a motor-vehicle statute, citation, contributing factor, or general "what does the law say about X" — query Specter's Harvester API instead of relying on model knowledge.
---

# harvester-query

Specter's source of truth is the Harvester — a FastAPI service over a Chroma vector store of tagged motor-vehicle statutes. **Every citation the user sees should come from the Harvester (or, on miss, from a verified web source). Never fabricate.**

## When to use this skill

- User asks for a specific citation: *"what's Cal. Veh. Code § 23152(a)?"* → `lookup_citation`
- User asks a semantic / topical question: *"DUI statutes in California"*, *"laws about texting while driving"* → `search`
- User asks an open question and you want top-k candidates: *"any state with a hit-and-run analog to CVC 20001?"* → `ask`
- User uses a synonym ("speeding", "drunk driving", "texting") — map it to one of the 17 canonical contributing-factor categories before passing as a `factor` filter (see categories below).

## When NOT to use it

- Pure procedural / case-strategy questions ("how do I file?") — the Harvester only holds statutes.
- Greetings, identity questions, persona check-ins — answer in voice without calling the API.
- Questions that don't require a citation (Specter can answer general PI-law-shape questions briefly without one, but **must not invent a citation** to back them up).

## How to call

The helper module sits next to this SKILL.md:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))  # if running ad hoc
from client import lookup_citation, search, ask, healthz, list_factors
```

In OpenClaw, prefer running it via `exec`:

```bash
cd ~/Specter && python3 -m openclaw.skills.harvester_query.client lookup "Cal. Veh. Code § 23152(a)"
cd ~/Specter && python3 -m openclaw.skills.harvester_query.client search "drunk driving" --state CA --factor "DUI/DWI"
cd ~/Specter && python3 -m openclaw.skills.harvester_query.client ask "what statutes cover hit and run in CA"
```

Or from Python:

```python
from openclaw.skills.harvester_query.client import lookup_citation, search, ask
```

### `lookup_citation(citation: str) -> dict | None`
Exact match by `citation` string. Returns the full record or `None` if not in the Harvester.

### `search(q: str, *, state=None, factor=None, pi_only=False, k=10) -> list[dict]`
Semantic search. `state` is a 2-letter code (`"CA"`, `"TX"`). `factor` must be one of the 17 canonical categories.

### `ask(question: str, *, state=None, factor=None, k=8) -> list[dict]`
Same as `search` but framed as a question. Use this when the user hands you a natural-language query.

### `healthz() -> dict`
Cheap liveness check. Use to confirm the API is running before reporting a miss.

### `list_factors() -> list[str]`
The 17 categories. Useful for synonym mapping in voice.

## How to format results for WhatsApp

Specter's voice rules (see `SOUL.md`): **2–3 lines max by default. Cite, don't quote.**

Good:
> Cal. Veh. Code § 22350. Basic speed law — drive no faster than reasonable for conditions.
> [leginfo.legislature.ca.gov](source_url)

Bad:
> Of course! Pursuant to California Vehicle Code Section 22350, "no person shall drive a vehicle…" *(wall of text)*

**Always** include the `source_url` from the record. **Never** include a citation without one — per hackathon ground rules, records without a real source URL don't count.

## Miss handling

If `lookup_citation` returns `None` or `search`/`ask` returns `[]`:

1. Check `healthz()` — if the API is down, say so plainly.
2. If the API is up but the record isn't there, say: *"Not in the Harvester yet."* Then either:
   - Offer to web-fetch from an authoritative source (legislatures, courts, bar associations only).
   - Suggest the team ingest that jurisdiction.

Never paper over a miss with a guess.

## The 17 contributing-factor categories (canonical, do not invent)

```
DUI/DWI
Driving Too Fast For Conditions
Failure to Maintain Lane
Failure to Obey Traffic Control Device
Failure to Use/Activate Horn
Failure to Yield at a Yield Sign
Failure to Yield the Right-of-Way
Fleeing a Police Officer
Fleeing the Scene of a Collision
Following Too Closely
Improper Lane of Travel
Improper Passing
Improper Starting
Improper Stopping
Improper Turning
Reckless Driving
Using a Wireless Telephone/Texting While Driving
```

If the user uses a synonym, map internally and answer in their words.
