import json
import os
from dotenv import load_dotenv
import voyageai
import chromadb
from collections import Counter

load_dotenv()

# config
VOYAGE_API_KEY  = os.getenv("VOYAGE_API_KEY")
CHROMA_PATH     = "./chroma_db"
COLLECTION_NAME = "pi_cases"
TOP_K           = 20  # number of similar cases to retrieve


# config (module-level so they're reused across calls)

vo         = voyageai.Client(api_key=VOYAGE_API_KEY)
chroma     = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma.get_collection(COLLECTION_NAME)


# =========================================================
# METADATA FILTERS
# Build a Chroma `where` clause from structured fact flags.
# Each filter narrows the result set BEFORE vector similarity.
# Used by the "what if" engine to recompute on changed facts.
# =========================================================

def build_filters(
    treatment_gap: bool = None,
    pre_existing: bool = None,
    surveillance: bool = None,
    contributory_negligence: bool = None,
    municipal: bool = None,
    plaintiff_won: bool = None,
    defendant_type: str = None,
    court: str = None,
    year_min: int = None,
) -> dict:
    """
    Returns a Chroma `where` filter dict, or None if no filters set.
    Only adds a condition if the value is explicitly True or False
    (None means "don't filter on this field").
    """
    conditions = []

    if treatment_gap is not None:
        conditions.append({"treatment_gap_present": {"$eq": treatment_gap}})
    if pre_existing is not None:
        conditions.append({"pre_existing_condition": {"$eq": pre_existing}})
    if surveillance is not None:
        conditions.append({"surveillance_used": {"$eq": surveillance}})
    if contributory_negligence is not None:
        conditions.append({"contributory_negligence_found": {"$eq": contributory_negligence}})
    if municipal is not None:
        conditions.append({"municipal_liability_case": {"$eq": municipal}})
    if plaintiff_won is not None:
        conditions.append({"plaintiff_won": {"$eq": plaintiff_won}})
    if defendant_type is not None:
        conditions.append({"defendant_type": {"$contains": defendant_type}})
    if court is not None:
        conditions.append({"court": {"$eq": court}})
    if year_min is not None:
        conditions.append({"year": {"$gte": year_min}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


# =========================================================
# AGGREGATE STATS
# Compute win rate, damages, and risk flags from a list
# of case metadata dicts returned by Chroma.
# =========================================================

def aggregate_stats(cases: list[dict]) -> dict:
    total = len(cases)
    if total == 0:
        return {}

    won  = sum(1 for c in cases if c.get("plaintiff_won") is True)
    lost = sum(1 for c in cases if c.get("plaintiff_won") is False)

    # Damages — only from real awards (>0, not split trial)
    real_awards = [
        c["damages_awarded"] for c in cases
        if isinstance(c.get("damages_awarded"), int)
        and c["damages_awarded"] > 0
    ]
    avg_damages = int(sum(real_awards) / len(real_awards)) if real_awards else None
    max_damages = max(real_awards) if real_awards else None

    # Risk flags frequency
    flags = {
        "credibility_issue":           sum(1 for c in cases if c.get("credibility_issue")),
        "pre_existing_condition":      sum(1 for c in cases if c.get("pre_existing_condition")),
        "treatment_gap_present":       sum(1 for c in cases if c.get("treatment_gap_present")),
        "surveillance_used":           sum(1 for c in cases if c.get("surveillance_used")),
        "contributory_negligence":     sum(1 for c in cases if c.get("contributory_negligence_found")),
        "expert_evidence_decisive":    sum(1 for c in cases if c.get("expert_evidence_decisive")),
    }

    # Most common deciding factors (top 5)
    deciding_factors = [
        c["deciding_factor"] for c in cases
        if c.get("deciding_factor")
    ]

    # Most common defence arguments (top 3)
    defence_args = [
        c["primary_defense_argument"] for c in cases
        if c.get("primary_defense_argument")
    ]

    # Injury type distribution
    injury_counter = Counter()
    for c in cases:
        injury_str = c.get("injury_type", "")
        if injury_str:
            for inj in injury_str.split(","):
                injury_counter[inj.strip()] += 1

    return {
        "total_similar_cases":   total,
        "plaintiff_won_count":   won,
        "plaintiff_lost_count":  lost,
        "win_rate":              round(won / (won + lost) * 100, 1) if (won + lost) > 0 else None,
        "avg_damages":           avg_damages,
        "max_damages":           max_damages,
        "damages_sample_size":   len(real_awards),
        "risk_flags":            flags,
        "deciding_factors":      deciding_factors[:5],
        "defence_arguments":     defence_args[:3],
        "injury_distribution":   dict(injury_counter.most_common(5)),
    }


# =========================================================
# CORE QUERY FUNCTION
# This is what everything else calls.
# =========================================================

def query_cases(
    facts: str,
    filters: dict = None,
    top_k: int = TOP_K,
    label: str = "baseline"
) -> dict:
    """
    Given plain English case facts, find the most similar
    historical Ontario PI cases and return structured results.

    Args:
        facts:   Plain English description of the case
        filters: Optional Chroma `where` dict from build_filters()
        top_k:   Number of similar cases to retrieve
        label:   Tag for this query (used in what-if comparisons)

    Returns:
        {
            label:       str,
            query:       str,
            cases:       list of metadata dicts,
            stats:       aggregated stats dict,
            top_cases:   top 5 cases for citation in memo
        }
    """
    # Embed the query
    result = vo.embed(
        [facts],
        model="voyage-law-2",
        input_type="query"
    )
    query_vector = result.embeddings[0]

    # Query Chroma
    query_kwargs = {
        "query_embeddings": [query_vector],
        "n_results": top_k,
        "include": ["metadatas", "distances", "documents"]
    }
    if filters:
        query_kwargs["where"] = filters

    chroma_results = collection.query(**query_kwargs)

    cases     = chroma_results["metadatas"][0]
    distances = chroma_results["distances"][0]
    documents = chroma_results["documents"][0]

    # Attach similarity score to each case
    for i, case in enumerate(cases):
        case["similarity_score"] = round(1 - distances[i], 3)
        case["embed_text"]       = documents[i]

    stats = aggregate_stats(cases)

    # Top 5 most similar for direct citation in memo
    top_cases = sorted(cases, key=lambda x: x["similarity_score"], reverse=True)[:5]

    return {
        "label":     label,
        "query":     facts,
        "cases":     cases,
        "stats":     stats,
        "top_cases": top_cases,
    }


# =========================================================
# WHAT-IF ENGINE
# Runs two queries — baseline and modified — and returns
# a diff so Claude can explain what changed and why.
# =========================================================

def what_if(
    original_facts: str,
    modified_facts: str,
    original_filters: dict = None,
    modified_filters: dict = None,
) -> dict:
    """
    Compares two query results to power the scenario engine.

    Returns both results plus a structured diff Claude can
    use to explain the legal significance of the change.
    """
    baseline = query_cases(
        original_facts,
        filters=original_filters,
        label="baseline"
    )
    scenario = query_cases(
        modified_facts,
        filters=modified_filters,
        label="scenario"
    )

    # Compute the diff
    b_stats = baseline["stats"]
    s_stats = scenario["stats"]

    win_rate_delta = None
    if b_stats.get("win_rate") is not None and s_stats.get("win_rate") is not None:
        win_rate_delta = round(s_stats["win_rate"] - b_stats["win_rate"], 1)

    damages_delta = None
    if b_stats.get("avg_damages") and s_stats.get("avg_damages"):
        damages_delta = s_stats["avg_damages"] - b_stats["avg_damages"]

    diff = {
        "win_rate_before":  b_stats.get("win_rate"),
        "win_rate_after":   s_stats.get("win_rate"),
        "win_rate_delta":   win_rate_delta,
        "damages_before":   b_stats.get("avg_damages"),
        "damages_after":    s_stats.get("avg_damages"),
        "damages_delta":    damages_delta,
        "cases_before":     b_stats.get("total_similar_cases"),
        "cases_after":      s_stats.get("total_similar_cases"),
    }

    return {
        "baseline": baseline,
        "scenario": scenario,
        "diff":     diff,
    }


# =========================================================
# CLI TEST
# =========================================================

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 1 — Baseline query")
    print("="*60)

    result = query_cases(
        "55 year old woman, rear-end motor vehicle accident on highway, "
        "soft tissue injury to neck and back, 8 month treatment gap, "
        "pre-existing degenerative disc disease, defendant is driver"
    )

    stats = result["stats"]
    print(f"\nFound {stats['total_similar_cases']} similar cases")
    print(f"Win rate: {stats['win_rate']}%")
    print(f"Avg damages: ${stats['avg_damages']:,}" if stats['avg_damages'] else "Avg damages: N/A")
    print(f"\nTop 3 similar cases:")
    for c in result["top_cases"][:3]:
        print(f"  • {c.get('case_name')} ({c.get('year')}) "
              f"won={c.get('plaintiff_won')} "
              f"similarity={c.get('similarity_score')}")

    print("\nTop deciding factors:")
    for f in result["stats"]["deciding_factors"][:3]:
        print(f"  • {f}")

    # ── What-if test ────────────────────────────────────────
    print("\n" + "="*60)
    print("TEST 2 — What if no treatment gap?")
    print("="*60)

    comparison = what_if(
        original_facts=(
            "55 year old woman, rear-end MVA, soft tissue injury, "
            "8 month treatment gap, pre-existing condition"
        ),
        modified_facts=(
            "55 year old woman, rear-end MVA, soft tissue injury, "
            "immediate physiotherapy, no treatment gap, pre-existing condition"
        ),
        original_filters=build_filters(treatment_gap=True),
        modified_filters=build_filters(treatment_gap=False),
    )

    diff = comparison["diff"]
    print(f"\nWin rate:  {diff['win_rate_before']}% → {diff['win_rate_after']}%  "
          f"(delta: {diff['win_rate_delta']:+}%)")
    if diff['damages_before'] and diff['damages_after']:
        print(f"Avg damages: ${diff['damages_before']:,} → ${diff['damages_after']:,}  "
              f"(delta: ${diff['damages_delta']:+,})")