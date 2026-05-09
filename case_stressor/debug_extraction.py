"""
debug_extraction.py
Run this to see exactly what Qwen is returning for your first case.
Usage: python debug_extraction.py
"""

import fitz
import httpx
import json
import re

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"
TEST_FILE = "cases/2003canlii23452.pdf"
MAX_CONTEXT_CHARS = 16000

PI_KEYWORDS = ["slip and fall","occupier liability","personal injury","motor vehicle accident",
    "rear-end collision","damages","negligence","soft tissue","chronic pain","concussion",
    "fracture","future income loss","plaintiff","tort","whiplash","mild traumatic brain injury",
    "catastrophic impairment"]

def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def extract_relevant_sections(text):
    lower = text.lower()
    keywords = ["overview","facts","analysis","damages","liability","causation",
                "credibility","conclusion","i find","the plaintiff","the defendant","judgment","decision"]
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

# Load the PDF
doc = fitz.open(TEST_FILE)
text = clean_text("".join(page.get_text() for page in doc))
doc.close()

relevant = extract_relevant_sections(text)
print(f"Sending {len(relevant)} chars to Qwen...\n")

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

  "injury_type": ["MVA","slip_and_fall","chronic_pain","soft_tissue","mTBI","fracture","orthopedic","psychological","other"],
  "location_type": ["road","sidewalk","retail","parking_lot","workplace","residential","pedestrian_ramp","other"],
  "defendant_type": ["driver","municipality","retailer","property_owner","insurer","other"],
  "plaintiff_age_group": ["young","middle","elderly","unknown"],

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

IMPORTANT:
- Use null when unknown.
- Use concise factual language.
- Do NOT invent details.
- citation should contain CanLII citation if present.
- case_summary must summarize the legal reasoning and outcome.

CASE TEXT:
{relevant}
"""

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

print("=" * 60)
print("RAW RESPONSE FROM QWEN:")
print("=" * 60)
print(raw)
print("=" * 60)

# Try to parse it
try:
    data = json.loads(raw)
    print("\nPARSED KEYS:")
    for k, v in data.items():
        print(f"  {k!r}: {repr(v)[:80]}")
except Exception as e:
    print(f"\nJSON PARSE FAILED: {e}")