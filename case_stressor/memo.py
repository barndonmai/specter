import os
import json
import httpx
from dotenv import load_dotenv
from query import query_cases, what_if, build_filters

load_dotenv()

# =========================================================
# CONFIG
# Switch LLM_BACKEND to "anthropic" at the hackathon
# when EvenUp provides API keys.
# =========================================================

LLM_BACKEND     = "anthropic"           # "ollama" | "anthropic"
OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_MODEL    = "gemma4:31b"
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-opus-4-7"


# =========================================================
# LLM CALL — unified interface for ollama and anthropic
# =========================================================

def call_llm(prompt: str, max_tokens: int = 2000) -> str:
    if LLM_BACKEND == "anthropic":
        return _call_anthropic(prompt, max_tokens)
    return _call_ollama(prompt, max_tokens)


def _call_ollama(prompt: str, max_tokens: int) -> str:
    response = httpx.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,
                "num_predict": max_tokens
            }
        },
        timeout=300
    )
    raw = response.json()["response"].strip()

    # Strip thinking blocks
    if "...done thinking." in raw:
        raw = raw.split("...done thinking.")[-1].strip()
    if "</think>" in raw:
        raw = raw.split("</think>")[-1].strip()

    return raw


def _call_anthropic(prompt: str, max_tokens: int) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    message = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# =========================================================
# FORMAT CASES FOR PROMPT
# Condenses top cases into a readable block for the LLM
# =========================================================

def format_cases_for_prompt(cases: list[dict], max_cases: int = 10) -> str:
    lines = []
    for i, c in enumerate(cases[:max_cases]):
        won      = "PLAINTIFF WON" if c.get("plaintiff_won") else "PLAINTIFF LOST"
        damages  = f"${c['damages_awarded']:,}" if isinstance(c.get("damages_awarded"), int) and c["damages_awarded"] > 0 else "N/A"
        citation = c.get("citation", "no citation")

        lines.append(
            f"{i+1}. {c.get('case_name', 'Unknown')} ({c.get('year', '?')}) [{citation}]\n"
            f"   Outcome: {won} | Damages: {damages} | Similarity: {c.get('similarity_score', '?')}\n"
            f"   Deciding factor: {c.get('deciding_factor', 'N/A')}\n"
            f"   Defence argument: {c.get('primary_defense_argument', 'N/A')}\n"
            f"   Flags: credibility={c.get('credibility_issue')} | "
            f"pre-existing={c.get('pre_existing_condition')} | "
            f"treatment_gap={c.get('treatment_gap_present')} | "
            f"surveillance={c.get('surveillance_used')}"
        )
    return "\n\n".join(lines)


# =========================================================
# BASELINE MEMO PROMPT
# =========================================================

def build_memo_prompt(facts: str, query_result: dict) -> str:
    stats = query_result["stats"]
    cases_text = format_cases_for_prompt(query_result["cases"])

    win_rate     = stats.get("win_rate", "N/A")
    avg_damages  = f"${stats['avg_damages']:,}" if stats.get("avg_damages") else "N/A"
    max_damages  = f"${stats['max_damages']:,}" if stats.get("max_damages") else "N/A"
    total_cases  = stats.get("total_similar_cases", 0)

    flags = stats.get("risk_flags", {})

    return f"""You are a senior Ontario personal injury litigation analyst.
A lawyer has described their client's case. You have retrieved {total_cases} comparable
Ontario court decisions from a structured database of real cases.

Your job is to write a concise, frank case assessment memo that a PI lawyer
would actually find useful — not generic legal advice, but specific intelligence
drawn from comparable Ontario decisions.

CASE FACTS PROVIDED BY LAWYER:
{facts}

COMPARABLE ONTARIO CASES ({total_cases} retrieved):
{cases_text}

AGGREGATE STATISTICS FROM COMPARABLE CASES:
- Win rate: {win_rate}% (based on {total_cases} comparable Ontario decisions)
- Average damages awarded: {avg_damages}
- Highest comparable award: {max_damages}
- Cases with credibility issues: {flags.get('credibility_issue', 0)}/{total_cases}
- Cases with pre-existing conditions: {flags.get('pre_existing_condition', 0)}/{total_cases}
- Cases with treatment gaps: {flags.get('treatment_gap_present', 0)}/{total_cases}
- Cases where surveillance was used: {flags.get('surveillance_used', 0)}/{total_cases}
- Cases where expert evidence was decisive: {flags.get('expert_evidence_decisive', 0)}/{total_cases}

Write the memo in this exact format:

---
PI CASE ASSESSMENT MEMO
Ontario Personal Injury Research Stack

CASE STRENGTH: [STRONG / MODERATE / WEAK / UNCERTAIN]
Win Rate (comparable cases): {win_rate}%
Average Damages (comparable cases): {avg_damages}
Based on: {total_cases} Ontario decisions

CASE SUMMARY
[2-3 sentences summarizing the key legal issues in this case]

ARGUMENTS IN YOUR FAVOUR
[3-4 bullet points — specific arguments that have worked in comparable Ontario cases]

OPPOSING COUNSEL WILL ARGUE
[3-4 bullet points — the exact arguments defence will make, drawn from comparable cases]

WEAKEST POINTS IN THIS CASE
[2-3 bullet points — the specific facts that hurt this case most, based on what decided comparable cases]

DAMAGES GUIDANCE
[2-3 sentences on realistic damages range, what heads of damage are recoverable, and what drove the highest awards in comparable cases]

SETTLEMENT GUIDANCE
[1-2 sentences on settlement positioning given the win rate and damages data]

KEY PRECEDENTS
[List the 3 most relevant cases with citation, outcome, and one sentence on why it matters]

TYPE "what if [changed fact]?" TO STRESS-TEST YOUR CASE
---

Be direct and specific. Reference actual cases from the comparable cases list.
Do not give generic legal disclaimers. Write like a senior litigator briefing a colleague.
"""


# =========================================================
# WHAT-IF MEMO PROMPT
# =========================================================

def build_whatif_prompt(
    original_facts: str,
    modified_facts: str,
    comparison: dict
) -> str:
    diff     = comparison["diff"]
    baseline = comparison["baseline"]
    scenario = comparison["scenario"]

    b_cases = format_cases_for_prompt(baseline["cases"], max_cases=5)
    s_cases = format_cases_for_prompt(scenario["cases"], max_cases=5)

    win_before  = diff.get("win_rate_before", "N/A")
    win_after   = diff.get("win_rate_after", "N/A")
    win_delta   = diff.get("win_rate_delta", 0)
    dmg_before  = f"${diff['damages_before']:,}" if diff.get("damages_before") else "N/A"
    dmg_after   = f"${diff['damages_after']:,}" if diff.get("damages_after") else "N/A"
    dmg_delta   = f"${diff['damages_delta']:+,}" if diff.get("damages_delta") else "N/A"

    direction = "improves" if (win_delta or 0) > 0 else "weakens"

    return f"""You are a senior Ontario personal injury litigation analyst.
A lawyer has stress-tested their case by changing one fact.
Explain what changed and why it matters legally.

ORIGINAL FACTS:
{original_facts}

MODIFIED FACTS (the "what if"):
{modified_facts}

IMPACT:
- Win rate: {win_before}% → {win_after}% ({win_delta:+}%)
- Avg damages: {dmg_before} → {dmg_after} ({dmg_delta})
- This change {direction} the case

BASELINE comparable cases (original facts):
{b_cases}

SCENARIO comparable cases (modified facts):
{s_cases}

Write a concise what-if analysis in this exact format:

---
SCENARIO ANALYSIS

IMPACT SUMMARY
Win rate: {win_before}% → {win_after}% ({win_delta:+}%)
Avg damages: {dmg_before} → {dmg_after}

WHY THIS FACT MATTERS
[2-3 sentences explaining the legal significance of this change in Ontario PI law.
Reference specific cases from above where this factor was decisive.]

WHAT CHANGES IN YOUR FAVOUR
[2-3 bullet points on how the case strengthens/weakens with this change]

WHAT STILL WORRIES ME
[1-2 bullet points on risks that remain even with this change]

REVISED STRATEGY
[1-2 sentences on how this changes litigation or settlement approach]
---

Be specific. Reference actual cases. No generic disclaimers. Dont add emoji
"""


# =========================================================
# PUBLIC API
# These are the two functions bot.py calls.
# =========================================================

def generate_memo(facts: str, filters: dict = None) -> str:
    """Generate a baseline case assessment memo."""
    result = query_cases(facts, filters=filters)
    prompt = build_memo_prompt(facts, result)
    return call_llm(prompt)


def generate_whatif_memo(
    original_facts: str,
    modified_facts: str,
    original_filters: dict = None,
    modified_filters: dict = None,
) -> str:
    """Generate a what-if scenario comparison memo."""
    comparison = what_if(
        original_facts,
        modified_facts,
        original_filters=original_filters,
        modified_filters=modified_filters,
    )
    prompt = build_whatif_prompt(original_facts, modified_facts, comparison)
    return call_llm(prompt)


# =========================================================
# CLI TEST
# =========================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 1 — Baseline memo")
    print("="*60 + "\n")

    memo = generate_memo(
        "55 year old woman, rear-end motor vehicle accident on highway, "
        "soft tissue injury to neck and back, 8 month treatment gap, "
        "pre-existing degenerative disc disease, defendant is driver"
    )
    print(memo)

    print("\n" + "="*60)
    print("TEST 2 — What if no treatment gap?")
    print("="*60 + "\n")

    whatif = generate_whatif_memo(
        original_facts=(
            "55 year old woman, rear-end MVA, soft tissue injury, "
            "8 month treatment gap, pre-existing condition"
        ),
        modified_facts=(
            "55 year old woman, rear-end MVA, soft tissue injury, "
            "immediate physiotherapy within 2 weeks, no treatment gap, "
            "pre-existing condition"
        ),
        original_filters=build_filters(treatment_gap=True),
        modified_filters=build_filters(treatment_gap=False),
    )
    print(whatif)