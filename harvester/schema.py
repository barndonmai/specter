"""
Canonical statute record. Every scraper outputs a list of these as JSON.

Keep this file dumb and stable — every track depends on it.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class StatuteRecord(BaseModel):
    id: str = Field(..., description="Stable slug: <state>-<code>-<section> e.g. ca-vc-23152-a")
    jurisdiction: str           # "California"
    state_code: str             # "CA"
    code: str                   # "Cal. Veh. Code"
    section: str                # "23152(a)"
    citation: str               # "Cal. Veh. Code § 23152(a)"
    title: Optional[str] = None
    text: str
    hierarchy_path: list[str] = []
    effective_date: Optional[str] = None
    source_url: str             # REQUIRED. Per ground rules.

    # Filled in by tagger/, not the scraper.
    # contributing_factors must be a strict subset of CONTRIBUTING_FACTORS
    # below — the held-out eval depends on canonical labels.
    contributing_factors: list[str] = []
    # Non-canonical PI-relevant labels (e.g., "Bicycle Violation",
    # "Equipment", "School Bus Violation"). NOT counted toward the eval, but
    # surfaced to paralegals so they can find statutes that don't fit the
    # standard 17 categories. Populated by seed_from_eval via
    # data/factor_synonyms.yaml.
    pi_context_tags: list[str] = []
    pi_relevant: Optional[bool] = None
    confidence: Optional[float] = None


# The 17 categories from the released CSV. Treat this as the source of truth.
CONTRIBUTING_FACTORS: list[str] = [
    "DUI/DWI",
    "Driving Too Fast For Conditions",
    "Failure to Maintain Lane",
    "Failure to Obey Traffic Control Device",
    "Failure to Use/Activate Horn",
    "Failure to Yield at a Yield Sign",
    "Failure to Yield the Right-of-Way",
    "Fleeing a Police Officer",
    "Fleeing the Scene of a Collision",
    "Following Too Closely",
    "Improper Lane of Travel",
    "Improper Passing",
    "Improper Starting",
    "Improper Stopping",
    "Improper Turning",
    "Reckless Driving",
    "Using a Wireless Telephone/Texting While Driving",
]


def make_id(state_code: str, code_slug: str, section: str) -> str:
    section_slug = section.lower().replace("(", "-").replace(")", "").replace(".", "-").replace(" ", "")
    return f"{state_code.lower()}-{code_slug.lower()}-{section_slug}".strip("-")
