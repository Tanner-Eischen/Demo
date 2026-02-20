PYTHON ?= python3
VENV ?= .venv

PIP := $(VENV)/bin/pip
PY  := $(VENV)/bin/python

.PHONY: help
help:
	@echo "Common targets:"
	@echo "  make setup        Create venv + install deps"
	@echo "  make api          Run FastAPI (reload)"
	@echo "  make worker       Run RQ worker"
	@echo "  make smoke        Compile check (no tests in MVP)"
	@echo "  make docker-up    docker compose up --build"
	@echo "  make docker-down  docker compose down -v"
	@echo "  make ci-smoke     Docker-based CI smoke"

.PHONY: setup
setup: $(VENV)/bin/activate

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt

.PHONY: api
api: setup
	PYTHONPATH=. $(VENV)/bin/uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: worker
worker: setup
	PYTHONPATH=. $(PY) worker/worker.py

.PHONY: smoke
smoke: setup
	$(PY) -m compileall backend worker

.PHONY: docker-up
docker-up:
	docker compose up --build

.PHONY: docker-down
docker-down:
	docker compose down -v --remove-orphans

.PHONY: ci-smoke
ci-smoke:
	./scripts/ci_smoke.sh
