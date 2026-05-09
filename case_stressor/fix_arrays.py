import json

with open("pi_cases.json", encoding="utf-8") as f:
    dataset = json.load(f)

array_fields = ["location_type", "defendant_type", "injury_type"]

fixed = 0
for case in dataset:
    for field in array_fields:
        val = case["metadata"].get(field)

        # Case 1: it's a plain string — wrap it in a list
        if isinstance(val, str):
            case["metadata"][field] = [val]
            fixed += 1

        # Case 2: it's a list — remove single-char garbage entries
        elif isinstance(val, list):
            cleaned = [
                item for item in val
                if isinstance(item, str) and len(item) > 1
            ]
            if len(cleaned) != len(val):
                fixed += 1
            case["metadata"][field] = cleaned

with open("pi_cases.json", "w", encoding="utf-8") as f:
    json.dump(dataset, f, indent=2, ensure_ascii=False)

print(f"Done — fixed {fixed} fields")