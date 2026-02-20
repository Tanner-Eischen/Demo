# AGENTS — vo-demo-generator (voice)

## Repo purpose
Local-first MVP that turns an uploaded screen recording (MP4) into a timestamped script, optional per-segment TTS WAVs, and a final muxed MP4 (+ optional SRT). Long-running work is executed via an **RQ** worker backed by **Redis**.

## Tech stack
- **Python 3.11**
- **FastAPI** API service (`backend/app/main.py`)
- **RQ + Redis** background jobs (`worker/worker.py`)
- **ffmpeg/ffprobe** for video/audio processing
- **Docker Compose** for local single-user deployment (`docker-compose.yml`)

## High-signal commands

### Run (recommended): Docker Compose
Create a clean `.env` (preferred over copying `.env.example` because inline comments can become part of values):

```bash
cat > .env <<'ENV'
# Z.ai (OpenAI-compatible)
ZAI_API_KEY=
ZAI_BASE_URL=https://api.z.ai/api/paas/v4/
ZAI_VISION_MODEL=glm-4.6v
ZAI_REWRITE_MODEL=glm-5

# TTS (optional)
TTS_ENDPOINT=
TTS_MODE=chatterbox_tts_json

# Redis / RQ
REDIS_URL=redis://redis:6379/0
RQ_QUEUE=default

# Storage
DATA_DIR=/data
ENV
```

Start services:
```bash
docker compose up --build
```

Smoke check:
```bash
curl -fsS http://localhost:8000/health
# API docs: http://localhost:8000/docs
```

### Run (no Docker): local dev
Prereqs: Redis running and `ffmpeg` available on your machine.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

export REDIS_URL=redis://localhost:6379/0
export RQ_QUEUE=default
export DATA_DIR=$(pwd)/data

# terminal 1: API
PYTHONPATH=. uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

# terminal 2: worker
PYTHONPATH=. python worker/worker.py
```

### Minimal verification (no formal test suite in this MVP)
```bash
python -m compileall backend worker
```

### Optional linting (not required by the repo)
If you want a lightweight linter without changing project deps:
```bash
python -m pip install ruff
ruff check backend worker
```

## Architecture notes
- API endpoints are defined in `backend/app/main.py`.
- Jobs are enqueued via `rq` in `backend/app/jobs.py` and executed by `worker/worker.py`.
- The main pipeline entrypoint is `backend/app/pipeline/pipeline_main.py`.
- Artifacts are stored under `./data/projects/<project_id>/` (see `docs/OPERATIONS.md`).

## CI expectations
This repo is typically validated by:
1) Python import/bytecode compilation (fast failure for syntax issues)
2) Docker Compose build + API health check

See: `.github/workflows/ci.yml` and `scripts/ci_smoke.sh`.
