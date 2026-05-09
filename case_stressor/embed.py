import json
import os
import time
from dotenv import load_dotenv
import voyageai
import chromadb

load_dotenv()

# config
VOYAGE_API_KEY  = os.getenv("VOYAGE_API_KEY")
JSON_FILE       = "pi_cases.json"
CHROMA_PATH     = "./chroma_db"
COLLECTION_NAME = "pi_cases"
BATCH_SIZE      = 10  # Voyage AI free tier handles 50 at a time



# We concatenate the most legally meaningful fields.
# This gives voyage-law-2 the best signal for similarity.
def build_embed_text(metadata: dict) -> str:
    parts = []

    if metadata.get("case_summary"):
        parts.append(metadata["case_summary"])

    if metadata.get("deciding_factor"):
        parts.append(f"Deciding factor: {metadata['deciding_factor']}")

    if metadata.get("primary_defense_argument"):
        parts.append(f"Primary defense: {metadata['primary_defense_argument']}")

    injury_types = metadata.get("injury_type") or []
    if injury_types:
        parts.append(f"Injury type: {', '.join(injury_types)}")

    location_types = metadata.get("location_type") or []
    if location_types:
        parts.append(f"Location: {', '.join(location_types)}")

    defendant_types = metadata.get("defendant_type") or []
    if defendant_types:
        parts.append(f"Defendant: {', '.join(defendant_types)}")

    return " | ".join(parts)



# metadata fro chroma
# Chroma only accepts str, int, float, bool
def flatten_metadata(metadata: dict) -> dict:
    flat = {}

    scalar_fields = [
        "case_name", "citation", "court", "year",
        "plaintiff_won", "damages_awarded", "damages_to_be_assessed",
        "contributory_negligence_found", "contributory_negligence_percentage",
        "credibility_issue", "pre_existing_condition", "surveillance_used",
        "treatment_gap_present", "future_income_loss_claimed",
        "expert_evidence_decisive", "causation_issue_present",
        "municipal_liability_case", "deciding_factor",
        "primary_defense_argument", "case_summary",
        "extraction_confidence", "source_file"
    ]

    for field in scalar_fields:
        val = metadata.get(field)
        if val is None:
            continue  # skip nulls — Chroma doesn't like them
        if isinstance(val, (str, int, float, bool)):
            flat[field] = val

    # Flatten list fields into comma-separated strings
    list_fields = ["injury_type", "location_type", "defendant_type", "plaintiff_age_group"]
    for field in list_fields:
        val = metadata.get(field)
        if val and isinstance(val, list):
            flat[field] = ",".join(str(v) for v in val if v)

    return flat


# main embed pipeline
def run_embed():
    print(f"\nLoading {JSON_FILE}...")
    with open(JSON_FILE, encoding="utf-8") as f:
        dataset = json.load(f)

    print(f"Loaded {len(dataset)} cases\n")

    vo = voyageai.Client(api_key=VOYAGE_API_KEY)

    # init chrome
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    # delete existing collection so we start fresh
    try:
        client.delete_collection(COLLECTION_NAME)
        print(f"Deleted existing collection '{COLLECTION_NAME}'")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}  # cosine similarity for legal text
    )

    ids       = []
    texts     = []
    metadatas = []

    for i, case in enumerate(dataset):
        meta = case["metadata"]
        embed_text = build_embed_text(meta)

        if not embed_text.strip():
            print(f"  X skipping case {i} — no embeddable text")
            continue

        ids.append(str(i))
        texts.append(embed_text)
        metadatas.append(flatten_metadata(meta))

    print(f"Embedding {len(texts)} cases with voyage-law-2...\n")

    all_embeddings = []
    total_batches  = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num in range(total_batches):
        start = batch_num * BATCH_SIZE
        end   = min(start + BATCH_SIZE, len(texts))
        batch = texts[start:end]

        print(f"  Batch {batch_num + 1}/{total_batches} ({start}–{end})...")

        try:
            result = vo.embed(
                batch,
                model="voyage-law-2",
                input_type="document"
            )
            all_embeddings.extend(result.embeddings)
            time.sleep(21)  # be kind to the free tier rate limit

        except Exception as e:
            print(f"  X batch {batch_num + 1} failed: {e}")
            raise

    print(f"\nStoring {len(all_embeddings)} vectors in Chroma...")

    for batch_num in range(total_batches):
        start = batch_num * BATCH_SIZE
        end   = min(start + BATCH_SIZE, len(ids))

        collection.add(
            ids=ids[start:end],
            embeddings=all_embeddings[start:end],
            documents=texts[start:end],
            metadatas=metadatas[start:end]
        )

    count = collection.count()
    print(f"\n{'='*50}")
    print(f"  Done — {count} cases stored in Chroma")
    print(f"  Path: {CHROMA_PATH}")
    print(f"  Collection: {COLLECTION_NAME}")
    print(f"{'='*50}\n")

    print("Running sanity test query: 'slip and fall on icy sidewalk'...")
    test_result = vo.embed(
        ["slip and fall on icy sidewalk, soft tissue injury, municipality defendant"],
        model="voyage-law-2",
        input_type="query"
    )
    results = collection.query(
        query_embeddings=test_result.embeddings,
        n_results=3
    )
    print("\nTop 3 similar cases:")
    for i, meta in enumerate(results["metadatas"][0]):
        print(f"  {i+1}. {meta.get('case_name')} ({meta.get('year')}) — won={meta.get('plaintiff_won')}")

    print("\nEmbed pipeline complete. Run query.py next.\n")


if __name__ == "__main__":
    run_embed()