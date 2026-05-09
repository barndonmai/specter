import json
from collections import Counter, defaultdict

JSON_FILE = "pi_cases.json"

def breakdown():
    with open(JSON_FILE, encoding="utf-8") as f:
        dataset = json.load(f)

    total = len(dataset)

    # ── Injury type counts ──────────────────────────────────────────────
    injury_counter = Counter()
    for case in dataset:
        for injury in (case["metadata"].get("injury_type") or []):
            injury_counter[injury] += 1

    # ── Location type counts ────────────────────────────────────────────
    location_counter = Counter()
    for case in dataset:
        for loc in (case["metadata"].get("location_type") or []):
            location_counter[loc] += 1

    # ── Defendant type counts ───────────────────────────────────────────
    defendant_counter = Counter()
    for case in dataset:
        for d in (case["metadata"].get("defendant_type") or []):
            defendant_counter[d] += 1

    # ── Court breakdown ─────────────────────────────────────────────────
    court_counter = Counter(
        c["metadata"].get("court", "unknown") for c in dataset
    )

    # ── Year breakdown ──────────────────────────────────────────────────
    year_counter = Counter(
        c["metadata"].get("year", "unknown") for c in dataset
    )

    # ── Win/loss by injury type ─────────────────────────────────────────
    injury_outcomes = defaultdict(lambda: {"won": 0, "lost": 0})
    for case in dataset:
        won = case["metadata"].get("plaintiff_won")
        for injury in (case["metadata"].get("injury_type") or []):
            if won is True:
                injury_outcomes[injury]["won"] += 1
            elif won is False:
                injury_outcomes[injury]["lost"] += 1

    # ── Flags ───────────────────────────────────────────────────────────
    credibility_cases  = sum(1 for c in dataset if c["metadata"].get("credibility_issue"))
    pre_existing       = sum(1 for c in dataset if c["metadata"].get("pre_existing_condition"))
    surveillance       = sum(1 for c in dataset if c["metadata"].get("surveillance_used"))
    treatment_gap      = sum(1 for c in dataset if c["metadata"].get("treatment_gap_present"))
    contrib_neg        = sum(1 for c in dataset if c["metadata"].get("contributory_negligence_found"))
    municipal          = sum(1 for c in dataset if c["metadata"].get("municipal_liability_case"))
    split_trial        = sum(1 for c in dataset if c["metadata"].get("damages_to_be_assessed"))

    won_total   = sum(1 for c in dataset if c["metadata"].get("plaintiff_won") is True)
    lost_total  = sum(1 for c in dataset if c["metadata"].get("plaintiff_won") is False)

    # ── Damages stats ───────────────────────────────────────────────────
    real_awards = [
        c["metadata"]["damages_awarded"]
        for c in dataset
        if isinstance(c["metadata"].get("damages_awarded"), int)
        and c["metadata"]["damages_awarded"] > 0
    ]
    avg_award = int(sum(real_awards) / len(real_awards)) if real_awards else 0
    max_award = max(real_awards) if real_awards else 0
    min_award = min(real_awards) if real_awards else 0

    # ── PRINT ───────────────────────────────────────────────────────────
    W = 54
    def header(title):
        print(f"\n{'─'*W}")
        print(f"  {title}")
        print(f"{'─'*W}")

    def bar(label, count, total, extra=""):
        pct = count / total * 100 if total else 0
        filled = int(pct / 4)
        b = "█" * filled + "░" * (25 - filled)
        print(f"  {label:<28} {b}  {count:>3}  ({pct:.0f}%){extra}")

    print(f"\n{'='*W}")
    print(f"  PI CASE DATASET BREAKDOWN")
    print(f"  {JSON_FILE}  —  {total} cases total")
    print(f"{'='*W}")

    # Overall outcome
    header("OVERALL OUTCOME")
    bar("Plaintiff won",  won_total,  total)
    bar("Plaintiff lost", lost_total, total)
    print(f"  {'Split trial / TBD':<28} {'':25}  {split_trial:>3}")

    # Damages
    header("DAMAGES (winning cases only)")
    print(f"  {'Cases with real award:':<30} {len(real_awards)}")
    print(f"  {'Average award:':<30} ${avg_award:,}")
    print(f"  {'Highest award:':<30} ${max_award:,}")
    print(f"  {'Lowest award:':<30} ${min_award:,}")

    # Injury type
    header("INJURY TYPE  (cases can have multiple)")
    for injury, count in injury_counter.most_common():
        w = injury_outcomes[injury]["won"]
        l = injury_outcomes[injury]["lost"]
        win_pct = f"  win rate {w/(w+l)*100:.0f}%" if (w + l) > 0 else ""
        bar(injury, count, total, win_pct)

    # Location
    header("LOCATION TYPE")
    for loc, count in location_counter.most_common():
        bar(loc, count, total)

    # Defendant
    header("DEFENDANT TYPE")
    for d, count in defendant_counter.most_common():
        bar(d, count, total)

    # Court
    header("COURT")
    for court, count in court_counter.most_common():
        bar(court, count, total)

    # Year
    header("YEAR")
    for year in sorted(year_counter):
        bar(str(year), year_counter[year], total)

    # Risk flags
    header("RISK FLAGS")
    flags = [
        ("Credibility issue",       credibility_cases),
        ("Pre-existing condition",  pre_existing),
        ("Contributory negligence", contrib_neg),
        ("Treatment gap",           treatment_gap),
        ("Surveillance used",       surveillance),
        ("Municipal liability",     municipal),
    ]
    for label, count in flags:
        bar(label, count, total)

    # Coverage gaps
    header("COVERAGE GAPS  (what you still need)")
    targets = {
        "MVA":           80,
        "slip_and_fall": 80,
        "mTBI":          20,
        "chronic_pain":  25,
        "fracture":      15,
        "psychological": 15,
        "catastrophic":  15,
    }
    print(f"  {'Category':<28} {'Have':>6}  {'Target':>7}  {'Gap':>6}")
    print(f"  {'─'*50}")
    for category, target in targets.items():
        have = injury_counter.get(category, 0)
        gap  = max(0, target - have)
        status = "✓ done" if gap == 0 else f"need {gap} more"
        print(f"  {category:<28} {have:>6}  {target:>7}  {status:>10}")

    print(f"\n{'='*W}\n")


if __name__ == "__main__":
    breakdown()