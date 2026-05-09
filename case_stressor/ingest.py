import glob
import json
import os
import re
import time
import warnings
from typing import Optional

import fitz  # pymupdf
import httpx

warnings.filterwarnings("ignore")

# config
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "gemma4:31b-cloud"

INPUT_FOLDER = "cases"
OUTPUT_FILE = "pi_cases.json"

MAX_CONTEXT_CHARS = 16000

PI_KEYWORDS = [
    "slip and fall",
    "occupier liability",
    "personal injury",
    "motor vehicle accident",
    "rear-end collision",
    "damages",
    "negligence",
    "soft tissue",
    "chronic pain",
    "concussion",
    "fracture",
    "future income loss",
    "plaintiff",
    "tort",
    "whiplash",
    "mild traumatic brain injury",
    "catastrophic impairment"
]

REQUIRED_FIELDS = [
    "case_name",
    "citation",
    "court",
    "year",
    "plaintiff_won",
    "injury_type",
    "case_summary",
    "deciding_factor",
    "primary_defense_argument",
]


# text cleaning
def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text


# loading the pdfs
def load_local_cases(folder: str = INPUT_FOLDER) -> list:
    results = []
    files = glob.glob(f"{folder}/*.pdf")

    if not files:
        print(f"No PDFs found in '{folder}/'")
        return results

    print(f"Found {len(files)} PDFs\n")

    for filepath in files:
        try:
            doc = fitz.open(filepath)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()

            text = clean_text(text)

            if len(text) < 1500:
                print(f"  X skipped short file: {filepath}")
                continue

            results.append({"filepath": filepath, "text": text})
            print(f"  loaded {filepath} ({len(text)} chars)")

        except Exception as e:
            print(f"  X failed {filepath}: {e}")

    return results


# pi filter
def is_pi_case(text: str) -> bool:
    text = text.lower()
    score = sum(1 for kw in PI_KEYWORDS if kw.lower() in text)
    return score >= 2


# relevant sections extract
def extract_relevant_sections(text: str) -> str:
    lower = text.lower()
    keywords = [
        "overview", "facts", "analysis", "damages", "liability",
        "causation", "credibility", "conclusion", "i find",
        "the plaintiff", "the defendant", "judgment", "decision"
    ]
    chunks = []
    for kw in keywords:
        idx = lower.find(kw)
        if idx != -1:
            start = max(0, idx - 1500)
            end = min(len(text), idx + 3500)
            chunk = text[start:end]
            if chunk not in chunks:
                chunks.append(chunk)

    if not chunks:
        chunks = [text[:6000], text[-6000:]]

    combined = "\n\n".join(chunks)
    return combined[:MAX_CONTEXT_CHARS]


# damages section extraction
# Grabs the last 4000 chars (where awards usually land)
# plus any paragraph containing a dollar sign
def extract_damages_sections(text: str) -> str:
    lower = text.lower()

    damage_keywords = [
        "i award", "i assess", "i find damages", "total damages",
        "judgment for", "damages of", "entitled to recover",
        "general damages", "special damages", "future care",
        "future income", "non-pecuniary", "pecuniary",
        "pain and suffering", "loss of income", "gross up",
        "prejudgment interest", "cost of care", "housekeeping",
        "fla", "family law act", "aggravated", "punitive"
    ]

    chunks = []

    # grabs the last 4000 chars
    chunks.append(text[-4000:])

    paragraphs = text.split(". ")
    for p in paragraphs:
        if "$" in p and len(p) > 20:
            chunks.append(p)

    for kw in damage_keywords:
        idx = lower.find(kw)
        if idx != -1:
            start = max(0, idx - 200)
            end = min(len(text), idx + 800)
            chunk = text[start:end]
            if chunk not in chunks:
                chunks.append(chunk)

    combined = "\n\n".join(chunks)
    return combined[:12000]


# json parsing — strips thinking block + markdown fences
def parse_model_response(raw: str) -> dict:
    if "...done thinking." in raw:
        raw = raw.split("...done thinking.")[-1].strip()

    if "</think>" in raw:
        raw = raw.split("</think>")[-1].strip()

    raw = raw.replace("```json", "").replace("```", "").strip()

    return json.loads(raw)


# json validtion
def validate_result(data: dict) -> bool:
    for field in REQUIRED_FIELDS:
        if field not in data:
            print(f"  X missing field: {field}")
            return False
    return True



# called when the main extraction returns null for damages
def extract_damages_fallback(case_text: str, case_name: str) -> Optional[dict]:
    """
    Focused second-pass extraction just for damages_awarded.
    Returns a dict with damages_awarded (int or 0) and a confidence float,
    or None if extraction fails entirely.
    """
    dollar_amounts = re.findall(r'\$[\d,]+(?:\.\d{2})?', case_text)
    damages_section = extract_damages_sections(case_text)

    prompt = f"""
You are a legal data extraction specialist. Your ONLY job is to find the
total damages awarded to the plaintiff in this Ontario court case.

SEARCH STRATEGY (do all of these):
1. Look for a "total" or final award line:
   e.g. "I award $X", "judgment for the plaintiff in the amount of $X",
        "total damages of $X", "damages are assessed at $X"
2. If no single total exists, ADD UP these heads of damage:
   - General / non-pecuniary damages
   - Special damages / out-of-pocket expenses
   - Future care costs
   - Future income loss / loss of earning capacity
   - Family Law Act (FLA) claims
   - Housekeeping / home maintenance loss
   - Gross-up for tax
   (Do NOT include prejudgment interest or costs — those are separate)
3. If contributory negligence applies, use the PRE-REDUCTION gross amount
4. If the plaintiff LOST, return 0
5. If damages were ordered to be assessed separately (a "split trial"),
   return -1 to flag this

All dollar amounts found in the document:
{dollar_amounts[:80]}

Relevant excerpts:
{damages_section}

Return ONLY valid JSON, no markdown, no explanation:
{{
  "damages_awarded": 150000,
  "damages_to_be_assessed": false,
  "damages_notes": "one sentence explaining what you found or why uncertain",
  "confidence": 0.85
}}

- damages_awarded must be an integer (dollars only, no cents)
- damages_awarded = -1 means split trial / separate assessment ordered
- damages_awarded = 0 means plaintiff lost
- NEVER return null — make your best estimate
"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0}
            },
            timeout=300
        )

        raw = response.json()["response"].strip()
        data = parse_model_response(raw)

        if "damages_awarded" not in data:
            print(f"  ✗ fallback missing damages_awarded for {case_name}")
            return None

        return data

    except Exception as e:
        print(f"  ✗ damages fallback failed for {case_name}: {e}")
        return None


# main extraction (full metadata)
def extract_case_metadata(case_text: str, filepath: str) -> Optional[dict]:
    relevant_text = extract_relevant_sections(case_text)
    damages_text = extract_damages_sections(case_text)

    # we inject a focused damages section separately so the model
    # has the best possible context for that field
    combined_context = f"""
=== GENERAL CASE TEXT ===
{relevant_text}

=== DAMAGES-FOCUSED EXCERPTS ===
{damages_text}
"""

    prompt = f"""
You are extracting structured litigation intelligence
from Ontario personal injury decisions.

Return ONLY VALID JSON.
No markdown.
No explanation.
No backticks.

Schema:

{{
  "case_name": "string",
  "citation": "string",
  "court": "ONSC | ONCA | LAT | other",
  "year": 2022,

  "plaintiff_won": true,
  "damages_awarded": 150000,
  "damages_to_be_assessed": false,

  "injury_type": [
    "MVA",
    "slip_and_fall",
    "chronic_pain",
    "soft_tissue",
    "mTBI",
    "fracture",
    "orthopedic",
    "psychological",
    "other"
  ],

  "location_type": [
    "road",
    "sidewalk",
    "retail",
    "parking_lot",
    "workplace",
    "residential",
    "pedestrian_ramp",
    "other"
  ],

  "defendant_type": [
    "driver",
    "municipality",
    "retailer",
    "property_owner",
    "insurer",
    "other"
  ],

  "plaintiff_age_group": [
    "young",
    "middle",
    "elderly",
    "unknown"
  ],

  "contributory_negligence_found": true,
  "contributory_negligence_percentage": 25,

  "credibility_issue": true,
  "pre_existing_condition": true,
  "surveillance_used": false,
  "treatment_gap_present": true,
  "future_income_loss_claimed": true,
  "expert_evidence_decisive": true,

  "causation_issue_present": true,
  "municipal_liability_case": false,

  "deciding_factor": "one concise sentence",
  "primary_defense_argument": "one concise sentence",
  "case_summary": "5-10 sentence concise factual summary",
  "extraction_confidence": 0.87
}}

IMPORTANT RULES:
- Use null for genuinely unknown fields EXCEPT damages_awarded (see below).
- Use concise factual language.
- Do NOT invent details.
- citation should contain CanLII citation if present.
- case_summary must summarize the legal reasoning and outcome.
- contributory_negligence_percentage: look for "X% responsible",
  "apportion liability X%", "contributory negligence of X%"

DAMAGES RULES (critical — read carefully):
- damages_awarded: Search EXHAUSTIVELY through the DAMAGES-FOCUSED EXCERPTS.
  (1) First look for a single total/judgment line.
  (2) If no total, SUM all heads: general damages + special damages +
      future care + future income loss + FLA claims + housekeeping.
      Do NOT include prejudgment interest or costs.
  (3) If contributory negligence applies, use the PRE-REDUCTION gross amount.
  (4) If plaintiff lost, set to 0.
  (5) If damages were sent to a separate assessment hearing (split trial),
      set damages_to_be_assessed to true and set damages_awarded to -1.
  (6) NEVER return null for damages_awarded. Use your best estimate.
      A rough estimate with lower extraction_confidence is better than null.

CASE TEXT:
{combined_context}
"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0}
            },
            timeout=600
        )

        raw = response.json()["response"].strip()
        data = parse_model_response(raw)

        if not validate_result(data):
            return None

        # If damages still came back null, run the targeted fallback
        if data.get("damages_awarded") is None:
            print(f"  ⚠ damages null after main pass — running fallback...")
            fallback = extract_damages_fallback(case_text, data.get("case_name", filepath))
            if fallback:
                data["damages_awarded"] = fallback["damages_awarded"]
                data["damages_to_be_assessed"] = fallback.get("damages_to_be_assessed", False)
                data["damages_notes"] = fallback.get("damages_notes", "")
                # Lower confidence since we needed a second pass
                data["extraction_confidence"] = min(
                    data.get("extraction_confidence", 0.5),
                    fallback.get("confidence", 0.5)
                )
                print(f"  ✓ fallback found damages: {data['damages_awarded']}")
            else:
                # Last resort: set to 0 for lost cases, flag for review
                data["damages_awarded"] = 0 if not data.get("plaintiff_won") else -2
                data["damages_notes"] = "Could not extract — flagged for manual review"
                print(f"  ✗ fallback also failed — flagged for review")

        data["source_file"] = filepath
        return data

    except Exception as e:
        print(f"  ✗ extraction failed: {e}")
        return None



# save
def save_dataset(dataset: list):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)


# PATCH EXISTING JSON
# Re-runs damages extraction only on cases where it's null.
# Run this once on your existing pi_cases.json before tonight's
# overnight ingest to clean up the 60 already-processed cases.

def patch_null_damages(json_file: str = OUTPUT_FILE):
    if not os.path.exists(json_file):
        print(f"No existing file at {json_file}")
        return

    with open(json_file, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    null_indices = [
        i for i, c in enumerate(dataset)
        if c["metadata"].get("damages_awarded") is None
    ]

    print(f"\nPATCH MODE: {len(null_indices)} cases with null damages_awarded\n")

    if not null_indices:
        print("Nothing to patch.")
        return

    patched = 0
    for i in null_indices:
        case = dataset[i]
        name = case["metadata"].get("case_name", f"case_{i}")
        text = case.get("full_text", "")

        print(f"  Patching [{i}] {name}")

        if not text:
            print(f"    ✗ no full_text stored — cannot re-extract")
            continue

        fallback = extract_damages_fallback(text, name)

        if fallback:
            dataset[i]["metadata"]["damages_awarded"] = fallback["damages_awarded"]
            dataset[i]["metadata"]["damages_to_be_assessed"] = fallback.get("damages_to_be_assessed", False)
            dataset[i]["metadata"]["damages_notes"] = fallback.get("damages_notes", "")
            save_dataset(dataset)
            patched += 1
            print(f"    ✓ ${fallback['damages_awarded']:,}  (confidence: {fallback.get('confidence', '?')})")
        else:
            # Mark for manual review rather than leaving null
            plaintiff_won = case["metadata"].get("plaintiff_won", False)
            dataset[i]["metadata"]["damages_awarded"] = 0 if not plaintiff_won else -2
            dataset[i]["metadata"]["damages_notes"] = "Flagged for manual review"
            save_dataset(dataset)
            print(f"    ✗ fallback failed — flagged")

    print(f"\nPatch complete — {patched}/{len(null_indices)} resolved")


# =========================================================
# STATS REPORT
# Quick sanity check on your dataset quality
# =========================================================

def print_stats(json_file: str = OUTPUT_FILE):
    if not os.path.exists(json_file):
        print(f"No file at {json_file}")
        return

    with open(json_file, encoding="utf-8") as f:
        dataset = json.load(f)

    total = len(dataset)
    won = sum(1 for c in dataset if c["metadata"].get("plaintiff_won") is True)
    lost = sum(1 for c in dataset if c["metadata"].get("plaintiff_won") is False)
    null_damages = sum(1 for c in dataset if c["metadata"].get("damages_awarded") is None)
    split_trial = sum(1 for c in dataset if c["metadata"].get("damages_to_be_assessed") is True)
    flagged = sum(1 for c in dataset if c["metadata"].get("damages_awarded") == -2)
    avg_conf = sum(
        c["metadata"].get("extraction_confidence") or 0
        for c in dataset
    ) / total if total else 0

    print(f"\n{'='*50}")
    print(f"DATASET STATS: {json_file}")
    print(f"{'='*50}")
    print(f"  Total cases:          {total}")
    print(f"  Plaintiff won:        {won} ({won/total*100:.1f}%)" if total else "")
    print(f"  Plaintiff lost:       {lost}")
    print(f"  Null damages:         {null_damages}  ← run patch_null_damages() if >0")
    print(f"  Split trial (no $):   {split_trial}")
    print(f"  Flagged for review:   {flagged}")
    print(f"  Avg confidence:       {avg_conf:.2f}")
    print(f"{'='*50}\n")


# MAIN PIPELINE
def run_pipeline():
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            dataset = json.load(f)
        processed = {x["metadata"]["source_file"] for x in dataset}
        print(f"Resuming — {len(dataset)} already processed\n")
    else:
        dataset = []
        processed = set()

    cases = load_local_cases(INPUT_FOLDER)
    print("\nStarting extraction...\n")

    for i, case in enumerate(cases):
        filepath = case["filepath"]

        if filepath in processed:
            print(f"[{i+1}/{len(cases)}] skipping {filepath}")
            continue

        print(f"\n[{i+1}/{len(cases)}] processing {filepath}")
        text = case["text"]

        if not is_pi_case(text):
            print("  ✗ not PI-related")
            continue

        start = time.time()
        result = extract_case_metadata(case_text=text, filepath=filepath)

        if not result:
            continue

        elapsed = time.time() - start

        dataset.append({"metadata": result, "full_text": text})
        save_dataset(dataset)

        damages_display = (
            f"${result['damages_awarded']:,}" if isinstance(result.get("damages_awarded"), int) and result["damages_awarded"] >= 0
            else "split trial" if result.get("damages_to_be_assessed")
            else "REVIEW" if result.get("damages_awarded") == -2
            else str(result.get("damages_awarded"))
        )

        print(
            f"  ✓ {result['case_name']} | "
            f"won={result['plaintiff_won']} | "
            f"damages={damages_display} | "
            f"confidence={result.get('extraction_confidence')} | "
            f"{elapsed:.0f}s"
        )

    print(f"\nDone — saved {len(dataset)} cases to {OUTPUT_FILE}")
    print_stats(OUTPUT_FILE)



# ENTRY

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "patch":
        # python ingest.py patch
        # → fixes null damages in existing pi_cases.json
        patch_null_damages()
        print_stats()

    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        # python ingest.py stats
        # → prints dataset quality report
        print_stats()

    else:
        # python ingest.py
        # → normal overnight ingest
        run_pipeline()