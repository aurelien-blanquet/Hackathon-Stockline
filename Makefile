PY ?= python3
.PHONY: setup run gen eval eval-llm schemas test demo

setup:            ## venv + deps
	$(PY) -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && cp -n .env.example .env || true

run:              ## API + UI on http://localhost:8000
	uvicorn app.main:app --reload --port 8000

gen:              ## regenerate the 15 curated cases (+ RANDOM=50 for volume)
	$(PY) -m tests.synthetic.generate --random $${RANDOM_N:-0}

eval:             ## accuracy benchmark (EXTRACTOR=llm to test Claude)
	$(PY) -m tests.eval --mode $${EXTRACTOR:-rules}

eval-llm:
	$(PY) -m tests.eval --mode llm --verbose

schemas:          ## regenerate shared_contracts/json_schema + examples after a contract change
	$(PY) -m scripts.export_schemas

test: gen eval    ## must stay green before every merge to main

demo:             ## the exact command used on stage
	EXTRACTOR=$${EXTRACTOR:-llm} uvicorn app.main:app --port 8000
