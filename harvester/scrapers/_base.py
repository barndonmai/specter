"""
Shared scraping helpers. Polite HTTP, JSON output to data/raw/<state>.json.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Iterable
import httpx
from harvester.schema import StatuteRecord

USER_AGENT = "SpecterHarvester/0.1 (hackathon; contact: team@specter.local)"
RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
        follow_redirects=True,
    )


def polite_sleep(seconds: float = 0.5) -> None:
    time.sleep(seconds)


def write_records(state_code: str, records: Iterable[StatuteRecord]) -> Path:
    out = RAW_DIR / f"{state_code.lower()}.json"
    payload = [r.model_dump() for r in records]
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"[harvester] wrote {len(payload):>5d} records → {out}")
    return out
