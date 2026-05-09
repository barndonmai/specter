import glob
import json
import os
import httpx
import warnings
import fitz  # pymupdf
import time
warnings.filterwarnings("ignore")

PI_KEYWORDS = [
    "slip and fall", "occupier", "negligence", "personal injury",
    "motor vehicle", "damages", "standard of care", "fracture",
    "soft tissue", "chronic pain", "loss of income", "plaintiff"
]

def load_local_cases(folder: str = "cases") -> list:
    results = []
    files = glob.glob(f"{folder}/*.pdf")
    if not files:
        print(f"No PDF files found in '{folder}/' folder")
        return results
    for filepath in files:
        try:
            doc = fitz.open(filepath)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            if text.strip():
                results.append({"text": text, "url": filepath})
                print(f"  ✓ loaded {filepath} ({len(text)} chars)")
            else:
                print(f"  ✗ no text in {filepath}")
        except Exception as e:
            print(f"  ✗ failed to read {filepath}: {e}")
    return results

def is_pi_case(text: str) -> bool:
    return any(kw in text.lower() for kw in PI_KEYWORDS)

def extract_outcome(case_text: str, url: str) -> dict:
    try:
        response = httpx.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma4:e2b",
                "prompt": f"""Extract from this Ontario PI case. Return JSON only. No markdown, no backticks, no explanation.

{{
  "plaintiff_won": true or false,
  "damages_awarded": number in dollars or null,
  "injury_type": "slip and fall" | "MVA" | "medical negligence" | "other",
  "location_type": "retail" | "residential" | "road" | "workplace" | "other",
  "plaintiff_age_group": "young" | "middle" | "elderly" | "unknown",
  "contributory_negligence_found": true or false or null,
  "contributory_negligence_percentage": number or null,
  "deciding_factor": "one sentence max",
  "defendant_type": "retailer" | "municipality" | "driver" | "other"
}}

CASE TEXT (beginning):
{case_text[:4000]}

CASE TEXT (end — verdict and damages are here):
{case_text[-4000:]}""",
                "stream": False
            },
            timeout=600
        )
        text = response.json()["response"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        outcome = json.loads(text)
        outcome["url"] = url
        return outcome
    except Exception as e:
        print(f"  ✗ extraction failed: {e}")
        return None

def run_pipeline():
    if os.path.exists("pi_cases.json"):
        with open("pi_cases.json") as f:
            dataset = json.load(f)
        already_done = {c["url"] for c in dataset}
        print(f"Resuming — {len(dataset)} cases already processed")
    else:
        dataset = []
        already_done = set()

    cases = load_local_cases("cases")
    print(f"\nFound {len(cases)} PDF files, processing...\n")

    for i, case in enumerate(cases[:3]):
        if case["url"] in already_done:
            print(f"[{i+1}/{len(cases)}] Skipping {case['url']}")
            continue

        print(f"[{i+1}/{len(cases)}] Processing {case['url']}")

        if not is_pi_case(case["text"]):
            print(f"  ✗ not a PI case, skipping")
            continue

        start_time = time.time()
        outcome = extract_outcome(case["text"], case["url"])
        if outcome:
            elapsed = time.time() - start_time
            dataset.append({"text": case["text"][:8000], **outcome})
            print(f"  ✓ {outcome['injury_type']} | won={outcome['plaintiff_won']} | damages={outcome['damages_awarded']} | took {elapsed:.0f}s")
            with open("pi_cases.json", "w") as f:
                json.dump(dataset, f, indent=2)

    print(f"\nDone. {len(dataset)} PI cases saved to pi_cases.json")

if __name__ == "__main__":
    run_pipeline()