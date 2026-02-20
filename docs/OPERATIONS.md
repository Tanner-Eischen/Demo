# OPERATIONS - vo-demo-generator (single-user)

## Storage
- `./data/projects/<project_id>/` contains:
  - `input.mp4`
  - `work/` (proxy, keyframes, intermediate wavs, demo run artifacts)
  - `exports/` (`final.mp4`, captions, narration mix)
  - `project.json`
  - `logs/job.log`

Backups: copy the entire project directory.

## Environment Variables
See `.env.example`.
- `DEMO_CAPTURE_EXECUTION_MODE=playwright_optional|playwright_required`
  - `playwright_optional`: deterministic dry-run fallback when Playwright/Chromium is unavailable.
  - `playwright_required`: fail demo capture immediately with dependency diagnostics.
- `INSTALL_PLAYWRIGHT=0|1`
  - `1` installs Playwright + Chromium during Docker image build (`api` and `worker`).

## Deterministic Playwright Provisioning
1. Fallback runtime (no browser dependencies):
   - `INSTALL_PLAYWRIGHT=0`
   - `DEMO_CAPTURE_EXECUTION_MODE=playwright_optional`
2. Playwright-enabled runtime:
   - `INSTALL_PLAYWRIGHT=1`
   - `DEMO_CAPTURE_EXECUTION_MODE=playwright_required`
3. Rebuild images after changing Playwright install mode:
   - `docker compose build --no-cache api worker`
4. Verify dependency status:
   - `curl -fsS http://localhost:8000/health/deps`

## CI Smoke Profiles
- Fallback profile:
  - `CI_SMOKE_PROFILE=fallback ./scripts/ci_smoke.sh`
  - Expects `/demo/run` to complete in `demo_capture_dry_run`.
- Playwright profile:
  - `CI_SMOKE_PROFILE=playwright INSTALL_PLAYWRIGHT=1 DEMO_CAPTURE_EXECUTION_MODE=playwright_required ./scripts/ci_smoke.sh`
  - Expects `/demo/run` to complete in `demo_capture_playwright`.

Both profiles validate:
- `POST /projects/{id}/timeline/actions/validate`
- `POST /projects/{id}/demo/run` + `GET /jobs/{id}`
- unified `POST /projects/{id}/render` + `GET /jobs/{id}`

## Troubleshooting
- ffmpeg missing: ensure containers built successfully (Dockerfiles install ffmpeg).
- TTS errors: leave `TTS_ENDPOINT` empty to use silence fallback.
- Z.ai errors: leave `ZAI_API_KEY` empty to use stub AI outputs.
- Timeline import errors: API returns line-specific parse details for timestamped txt and SRT imports.
- Playwright missing: check `/health/deps`, then install browser binaries (`playwright install chromium`) or switch to `playwright_optional`.

## Performance Tips
- Use proxy fps `8-12` for UI demos.
- Keep segment max `<= 8s` to avoid overly long narration lines.
