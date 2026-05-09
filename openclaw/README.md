# OpenClaw integration

This folder holds everything OpenClaw / Specter (the WhatsApp agent) needs that doesn't belong in the data pipeline.

## Layout

```
openclaw/
├── skills/                 # AgentSkills Specter loads at runtime
│   ├── harvester_query/    # Query the FastAPI Harvester for citations / search / ask
│   └── citation_format/    # Normalize citation strings before lookup
└── README.md               # this file

Folder names use underscores so they're valid Python package names
(`from openclaw.skills.harvester_query.client import ...`). OpenClaw's skill
discovery is name-agnostic — it just looks for `SKILL.md`.
```

## Wiring it into your local OpenClaw

Each teammate who runs Specter locally should symlink the skills into their workspace:

```bash
# From the repo root:
mkdir -p ~/.openclaw/workspace/skills
ln -sf "$PWD/openclaw/skills/harvester_query"   ~/.openclaw/workspace/skills/harvester_query
ln -sf "$PWD/openclaw/skills/citation_format"   ~/.openclaw/workspace/skills/citation_format
```

OpenClaw discovers skills under `~/.openclaw/workspace/skills/*/SKILL.md` automatically — no restart needed for new skills, but you may need a `openclaw gateway restart` if a skill isn't picked up after a few seconds.

## Required env

The Harvester client reads `SPECTER_API` (defaults to `http://127.0.0.1:8000`). Set it in your shell or in `~/.openclaw/workspace/.env` if you run the API on a different host/port:

```bash
export SPECTER_API=http://127.0.0.1:8000
```

## Python deps

The `harvester_query` client uses `httpx` (already in `requirements.txt`). Run `make install` from the repo root once before invoking the skill so the import works.

The `citation_format` skill is pure stdlib — no install needed.

## Persona

`SOUL.md` and `IDENTITY.md` (at repo root) define how Specter talks. Skills define what tools she has and when to reach for them. Keep them separate.
