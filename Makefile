.PHONY: install seed ingest tag load serve eval clean demo

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

# Pretty terminal demo of every endpoint, showing off multi-state coverage
demo:
	@$(PY) scripts/pretty.py health
	@$(PY) scripts/pretty.py factors
	@echo "\n### Citation lookups across states ###"
	@$(PY) scripts/pretty.py lookup "Cal. Veh. Code § 23152(a)"
	@$(PY) scripts/pretty.py lookup "Tex. Penal Code § 49.04"
	@$(PY) scripts/pretty.py lookup "Fla. Stat. § 316.183"
	@echo "\n### Same query, three states (cross-jurisdiction comparison) ###"
	@$(PY) scripts/pretty.py search "drunk driving" --state CA --k 3
	@$(PY) scripts/pretty.py search "drunk driving" --state TX --k 3
	@$(PY) scripts/pretty.py search "drunk driving" --state FL --k 3
	@echo "\n### Factor-filtered search (official 17-cat schema) ###"
	@$(PY) scripts/pretty.py search "running a red light" --state CA --factor "Failure to Obey Traffic Control Device" --k 3
	@$(PY) scripts/pretty.py search "turning at intersection" --factor "Improper Turning" --k 5
	@echo "\n### Open-ended search across ALL states ###"
	@$(PY) scripts/pretty.py search "speeding" --k 5
	@$(PY) scripts/pretty.py search "hit and run" --k 5
	@$(PY) scripts/pretty.py search "texting while driving" --k 5
	@echo "\n### Conversational /ask endpoint ###"
	@$(PY) scripts/pretty.py ask "what statutes apply when someone flees the scene of an accident" --k 3
	@$(PY) scripts/pretty.py ask "what is the Texas equivalent of California's DUI law" --state TX --k 3
