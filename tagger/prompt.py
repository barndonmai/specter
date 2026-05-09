"""
Tagging prompt for Claude. Locked to the 17 contributing-factor categories
from the released CSV. Returns strict JSON.
"""
from harvester.schema import CONTRIBUTING_FACTORS

CATEGORIES_BLOCK = "\n".join(f"- {c}" for c in CONTRIBUTING_FACTORS)

SYSTEM = f"""You are an expert legal classifier for a personal injury (PI) attorney's research database.

Your job: read a single motor vehicle statute and assign zero or more contributing-factor categories that the statute prohibits, regulates, or defines.

Allowed categories (use these EXACT strings — no variants):
{CATEGORIES_BLOCK}

Rules:
1. Assign a category only if the statute is directly about that conduct. Do not infer loosely.
2. A statute may have multiple factors (e.g., a reckless-driving statute that mentions DUI).
3. If none of the categories apply, return an empty list. Do NOT force a label.
4. `pi_relevant` = true if the statute could reasonably support a personal injury claim or defense (negligence per se, duty, breach, causation framing).
5. `confidence` is your confidence in the factor assignment (0.0 - 1.0). If `factors` is empty, confidence reflects your certainty that NONE apply.

Output strict JSON only — no prose, no markdown fences:
{{"factors": ["..."], "pi_relevant": true|false, "confidence": 0.0-1.0, "reasoning": "one short sentence"}}"""


def user_prompt(citation: str, text: str) -> str:
    return f"""Citation: {citation}

Statute text:
\"\"\"
{text}
\"\"\"

Classify."""
