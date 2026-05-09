import os
import sys
from memo import generate_memo, generate_whatif_memo
from query import build_filters

# =========================================================
# WHAT-IF PARSER
# Reads the lawyer's "what if" message and returns
# modified facts + the right metadata filter
# =========================================================

def parse_whatif(original_facts: str, message: str) -> tuple[str, dict, dict]:
    """
    Returns (modified_facts, original_filters, modified_filters)
    """
    msg = message.lower()

    # Strip "what if" prefix to get the changed fact
    changed = message
    for prefix in ["what if ", "what if there was ", "what if there were ",
                   "what if the ", "what if my client had ", "what if no "]:
        if msg.startswith(prefix):
            changed = message[len(prefix):]
            break

    # Build modified facts string
    modified_facts = f"{original_facts}. Scenario change: {changed}"

    # Map to metadata filters
    original_filters = {}
    modified_filters = {}

    if any(x in msg for x in ["no treatment gap", "immediate treatment",
                                "physio within", "immediate physio",
                                "no gap in treatment"]):
        original_filters = build_filters(treatment_gap=True)
        modified_filters = build_filters(treatment_gap=False)

    elif any(x in msg for x in ["treatment gap", "gap in treatment",
                                  "delayed treatment", "no treatment"]):
        original_filters = build_filters(treatment_gap=False)
        modified_filters = build_filters(treatment_gap=True)

    elif any(x in msg for x in ["no pre-existing", "no pre existing",
                                  "no prior condition", "healthy before"]):
        original_filters = build_filters(pre_existing=True)
        modified_filters = build_filters(pre_existing=False)

    elif any(x in msg for x in ["pre-existing", "pre existing",
                                  "prior condition", "had before"]):
        original_filters = build_filters(pre_existing=False)
        modified_filters = build_filters(pre_existing=True)

    elif any(x in msg for x in ["surveillance", "video footage",
                                  "surveillance footage"]):
        original_filters = build_filters(surveillance=False)
        modified_filters = build_filters(surveillance=True)

    elif any(x in msg for x in ["no surveillance", "no footage",
                                  "no video"]):
        original_filters = build_filters(surveillance=True)
        modified_filters = build_filters(surveillance=False)

    elif any(x in msg for x in ["municipality", "city", "town",
                                  "municipal defendant"]):
        original_filters = None
        modified_filters = build_filters(municipal=True)

    elif any(x in msg for x in ["contributory negligence", "partially at fault",
                                  "shared fault", "plaintiff at fault"]):
        original_filters = build_filters(contributory_negligence=False)
        modified_filters = build_filters(contributory_negligence=True)

    elif any(x in msg for x in ["no contributory", "not at fault",
                                  "fully defendant fault"]):
        original_filters = build_filters(contributory_negligence=True)
        modified_filters = build_filters(contributory_negligence=False)

    elif any(x in msg for x in ["onca", "court of appeal", "appeal court"]):
        original_filters = None
        modified_filters = build_filters(court="ONCA")

    elif any(x in msg for x in ["after 2015", "recent cases", "last 10 years"]):
        original_filters = None
        modified_filters = build_filters(year_min=2015)

    elif any(x in msg for x in ["after 2018", "last 5 years", "recent"]):
        original_filters = None
        modified_filters = build_filters(year_min=2018)

    # If no filter matched, just use the text change — semantic search handles it
    return modified_facts, original_filters or None, modified_filters or None


# =========================================================
# PRINT HELPERS
# =========================================================

def divider():
    print("\n" + "="*60 + "\n")

def thinking(msg: str):
    print(f"\n  ⏳ {msg}...\n")


# =========================================================
# MAIN CLI LOOP
# =========================================================

def run():
    os.system("cls" if os.name == "nt" else "clear")

    print("="*60)
    print("  PI CASE STRESS-TESTER")
    print("  Ontario Personal Injury Research Stack")
    print("  340 real Ontario decisions | Powered by voyage-law-2")
    print("="*60)
    print()
    print("  Describe your client's case in plain English.")
    print("  Then type  'what if [changed fact]?'  to stress-test.")
    print("  Type 'new' for a new case or 'quit' to exit.")
    print()

    current_facts = None

    while True:
        try:
            # ── Get input ───────────────────────────────────────
            if current_facts:
                user_input = input("› ").strip()
            else:
                user_input = input("Describe your case: ").strip()

            if not user_input:
                continue

            # ── Commands ────────────────────────────────────────
            if user_input.lower() in ["quit", "exit", "q"]:
                print("\nGood luck in court.\n")
                sys.exit(0)

            if user_input.lower() in ["new", "new case", "reset"]:
                current_facts = None
                divider()
                print("Describe your new case:")
                continue

            # ── What-if query ────────────────────────────────────
            if user_input.lower().startswith("what if"):
                if not current_facts:
                    print("\n  Please describe your case first before running a what-if.\n")
                    continue

                thinking("Running scenario analysis against 340 Ontario decisions")

                modified_facts, orig_filters, mod_filters = parse_whatif(
                    current_facts, user_input
                )

                memo = generate_whatif_memo(
                    original_facts=current_facts,
                    modified_facts=modified_facts,
                    original_filters=orig_filters,
                    modified_filters=mod_filters,
                )

                divider()
                print(memo)
                divider()
                print("  Type another 'what if?' or 'new' for a new case.")
                print()
                continue

            # ── Baseline query ───────────────────────────────────
            current_facts = user_input
            thinking("Searching 340 Ontario PI decisions")

            memo = generate_memo(current_facts)

            divider()
            print(memo)
            divider()
            print("  Type 'what if [changed fact]?' to stress-test this case.")
            print("  Example: what if there was no treatment gap?")
            print("  Example: what if the defendant is a municipality?")
            print("  Example: what if there was surveillance footage?")
            print()

        except KeyboardInterrupt:
            print("\n\nGood luck in court.\n")
            sys.exit(0)

        except Exception as e:
            print(f"\n  Error: {e}\n")
            continue


# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":
    run()