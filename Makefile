.PHONY: install seed ingest tag load serve eval clean

export PYTHONPATH := .
PY ?= python3

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
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

eval:
	$(PY) -m evals.run_eval

clean:
	rm -rf .chroma data/tagged/*.json
