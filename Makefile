.PHONY: install dev test eval seed demo lint contract e2e graphs api web gigsim up down

PY ?= python

install:
	$(PY) -m pip install -e ".[dev]"
	cd apps/web && npm install

seed:            ## generate personas, jobs, gold labels (deterministic, seeded)
	$(PY) -m gigsim.datagen --seed 1337

gigsim:          ## run the marketplace simulator on :8081
	$(PY) -m gigsim

api:
	GIGBID_SERVICES=real uvicorn apps.api.main:app --reload --port 8000

web:
	cd apps/web && npm run dev

dev:             ## everything locally without docker (simulator + api + web)
	@echo "run in 3 terminals: make gigsim | make api | make web   (or: docker compose -f infra/docker-compose.yml up)"

test:            ## unit + contract + integration (no network, stub LLM)
	$(PY) -m pytest -q

contract:
	$(PY) -m pytest -q tests/contract

e2e:
	cd apps/web && npx playwright test

eval:            ## retrieval metrics, decision metrics, fixed GigSim reply-rate run -> evals/results/*.json
	$(PY) -m evals.runners.rag_eval
	$(PY) -m evals.runners.decision_eval
	$(PY) -m evals.runners.gigsim_outcomes

eval-smoke:
	$(PY) -m evals.runners.rag_eval --smoke
	$(PY) -m evals.runners.decision_eval --smoke
	$(PY) -m evals.runners.check_thresholds

demo:            ## one job from inbox to approved proposal in the terminal (stub LLM, GigSim)
	$(PY) -m evals.runners.demo

graphs:          ## render both LangGraph graphs from code
	$(PY) -m agent.render_graphs

lint:
	ruff check .

up:
	docker compose -f infra/docker-compose.yml up --build

down:
	docker compose -f infra/docker-compose.yml down
