.PHONY: install seed ingest tag load serve eval clean demo demo-realistic demo-big-ass-query browse sources authority

export PYTHONPATH := .
# Auto-prefer the project venv if it exists; otherwise fall back to system python3.
PY ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python3)

install:
	$(PY) -m pip install -r requirements.txt

seed:
	$(PY) scripts/seed_from_eval.py

ingest:
	$(PY) -m harvester.scrapers.ca
	$(PY) -m harvester.scrapers.ny
	$(PY) -m harvester.scrapers.tx
	$(PY) -m harvester.scrapers.fl
	$(PY) -m harvester.scrapers.il

tag:
	$(PY) -m tagger.tag data/raw

load:
	$(PY) scripts/load_chroma.py

serve:
	.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

eval:
	$(PY) -m evals.run_eval

clean:
	rm -rf .chroma data/tagged/*.json

# Interactive Chroma browser. View every record, every field, with keyboard nav.
browse:
	$(PY) scripts/browse.py

# Show the catalog of authoritative sources (kinds, jurisdictions, URLs).
sources:
	$(PY) scripts/pretty.py sources

# Full case-intake demo: walks the Anaheim phantom-vehicle hypo end-to-end
# through every layer of Specter (statutes, factor filters, legal_topics,
# authority routing, cross-jurisdiction). This is the showcase demo.
demo-big-ass-query:
	PY=$(PY) bash scripts/case_demo.sh

# Show the AUTHORITY MAP: which sources are authoritative for what.
# This is the actual wiki deliverable from the hackathon brief.
authority:
	@echo "\n### Routing by research need ###"
	@$(PY) scripts/pretty.py authority --need "case law"
	@$(PY) scripts/pretty.py authority --need "damages"
	@$(PY) scripts/pretty.py authority --need "court rules"
	@$(PY) scripts/pretty.py authority --need "ethics"
	@echo "\n### Routing by legal_topic + jurisdiction ###"
	@$(PY) scripts/pretty.py authority --legal-topic "DUI-related behavior" --state CA
	@$(PY) scripts/pretty.py authority --legal-topic "hit and run"
	@$(PY) scripts/pretty.py authority --legal-topic "distracted driving"

# Realistic paralegal/attorney chaos queries — how a real human types,
# not how a law professor types. This is the demo that wins judges.
demo-realistic:
	@$(PY) scripts/pretty.py health
	@echo "\n### 🚨 Frantic intake calls (vague, emotional, fragmented) ###"
	@$(PY) scripts/pretty.py search "client just got rear-ended by a drunk driver in california" --k 4
	@$(PY) scripts/pretty.py search "driver fled from police and caused an accident" --k 4
	@$(PY) scripts/pretty.py search "woman texting rear-ended my client" --k 4
	@$(PY) scripts/pretty.py search "truck driver ran a red light and totaled the car" --k 4
	@echo "\n### 😡 Pissed-off client describing the accident ###"
	@$(PY) scripts/pretty.py search "other driver was going way too fast on the highway" --k 4
	@$(PY) scripts/pretty.py search "they didn't even stop after hitting me" --k 4
	@$(PY) scripts/pretty.py search "guy was tailgating then slammed into me" --k 4
	@$(PY) scripts/pretty.py search "cut me off and forced me off the road" --k 4
	@echo "\n### 🤔 Paralegal researching for a brief ###"
	@$(PY) scripts/pretty.py search "what counts as reckless driving in florida" --jurisdiction Florida --k 4
	@$(PY) scripts/pretty.py search "unsafe lane change causing an accident" --state TX --k 4
	@$(PY) scripts/pretty.py search "accident near a school zone with kids crossing" --k 4
	@$(PY) scripts/pretty.py search "handheld phone ban while driving" --legal-topic "distracted driving" --k 6
	@echo "\n### 💸 Insurance / coverage angle ###"
	@$(PY) scripts/pretty.py search "unlicensed driver caused a crash" --k 4
	@$(PY) scripts/pretty.py ask "drunk driver caused property damage and bodily injury" --legal-topic "DUI-related behavior" --k 4
	@$(PY) scripts/pretty.py ask "plaintiff rear-ended at a red light by a distracted driver" --k 4
	@echo "\n### 🌧️ Specific scenario stress tests ###"
	@$(PY) scripts/pretty.py search "accident in heavy rain wet pavement poor visibility" --k 4
	@$(PY) scripts/pretty.py search "school bus stopped driver passed anyway" --k 4
	@$(PY) scripts/pretty.py search "failure to yield to ambulance with lights and siren" --k 4
	@$(PY) scripts/pretty.py search "street racing illegal contest of speed" --k 4
	@echo "\n### 🧠 Conversational paralegal questions ###"
	@$(PY) scripts/pretty.py ask "client was hit and the driver took off, what statutes can I cite" --k 5
	@$(PY) scripts/pretty.py ask "PA equivalent of California vehicle code 23152" --jurisdiction Pennsylvania --legal-topic "DUI-related behavior" --k 4
	@$(PY) scripts/pretty.py ask "reckless driving causing serious bodily injury" --k 4
	@echo "\n### 🎯 The showstopper — messy multi-violation scenario ###"
	@$(PY) scripts/pretty.py ask "this jerk was speeding and on his phone and ran a red light and slammed into my client what laws did he break" --k 8

# Pretty terminal demo of every endpoint. Showcases multi-state coverage AND
# the normalized legal_topic abstraction layer.
demo:
	@$(PY) scripts/pretty.py health
	@$(PY) scripts/pretty.py factors
	@$(PY) scripts/pretty.py topics
	@echo "\n### Citation lookups across 4 jurisdictions ###"
	@$(PY) scripts/pretty.py lookup "Cal. Veh. Code § 23152(a)"
	@$(PY) scripts/pretty.py lookup "Tex. Penal Code § 49.04"
	@$(PY) scripts/pretty.py lookup "Fla. Stat. § 316.183"
	@$(PY) scripts/pretty.py lookup "75 Pa. C.S. § 3361"
	@echo "\n### Same query, four states (cross-jurisdiction comparison) ###"
	@$(PY) scripts/pretty.py search "drunk driving" --state CA --k 2
	@$(PY) scripts/pretty.py search "drunk driving" --state TX --k 2
	@$(PY) scripts/pretty.py search "drunk driving" --state FL --k 2
	@$(PY) scripts/pretty.py search "drunk driving" --state PA --k 2
	@echo "\n### Normalized legal_topic filter (semantic abstraction layer) ###"
	@echo "# 'speeding' across ALL jurisdictions, regardless of how each state spelled it:"
	@$(PY) scripts/pretty.py search "speed limit" --legal-topic speeding --k 5
	@echo "# 'distracted driving' — unifies Texting/Wireless Telephone/etc.:"
	@$(PY) scripts/pretty.py search "phone while driving" --legal-topic "distracted driving" --k 5
	@echo "# 'DUI-related behavior' — maps DUI/DWI/Intoxication/etc.:"
	@$(PY) scripts/pretty.py search "drunk" --legal-topic "DUI-related behavior" --k 5
	@echo "\n### Raw factor filter (17-cat schema, also still works) ###"
	@$(PY) scripts/pretty.py search "turning at intersection" --factor "Improper Turning" --k 5
	@echo "\n### Open-ended search across ALL states ###"
	@$(PY) scripts/pretty.py search "hit and run" --k 5
	@echo "\n### High-confidence-only retrieval ###"
	@$(PY) scripts/pretty.py search "reckless driving" --min-confidence 0.9 --k 5
	@echo "\n### Conversational /ask endpoint ###"
	@$(PY) scripts/pretty.py ask "what statutes apply when someone flees the scene of an accident" --k 3
	@$(PY) scripts/pretty.py ask "what is the Texas equivalent of California's DUI law" --jurisdiction Texas --k 3
