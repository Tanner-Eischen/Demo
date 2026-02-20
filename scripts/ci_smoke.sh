#!/usr/bin/env bash
set -euo pipefail

# CI smoke profiles:
# - fallback: Playwright intentionally unavailable; validate explicit dry-run path.
# - playwright: Playwright + Chromium available; validate real browser capture path.
#
# Shared checks:
# - build docker images
# - bring up redis/api/worker
# - wait for API /health and inspect /health/deps
# - upload synthetic MP4
# - import timeline (narration + actions) and validate actions
# - queue /demo/run and poll /jobs/{id}
# - patch narration mode to unified, queue /render, poll /jobs/{id}
# - assert expected demo mode and unified render result

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SMOKE_PROFILE="${CI_SMOKE_PROFILE:-fallback}"
case "$SMOKE_PROFILE" in
  fallback)
    EXPECTED_DEMO_MODE="demo_capture_dry_run"
    DEFAULT_PLAYWRIGHT_INSTALL="0"
    DEFAULT_CAPTURE_MODE="playwright_optional"
    EXPECTED_PLAYWRIGHT_OK="false"
    EXPECTED_PLAYWRIGHT_REQUIRED="false"
    ;;
  playwright)
    EXPECTED_DEMO_MODE="demo_capture_playwright"
    DEFAULT_PLAYWRIGHT_INSTALL="1"
    DEFAULT_CAPTURE_MODE="playwright_required"
    EXPECTED_PLAYWRIGHT_OK="true"
    EXPECTED_PLAYWRIGHT_REQUIRED="true"
    ;;
  *)
    echo "Unsupported CI_SMOKE_PROFILE='$SMOKE_PROFILE' (expected: fallback|playwright)"
    exit 1
    ;;
esac

INSTALL_PLAYWRIGHT="${INSTALL_PLAYWRIGHT:-$DEFAULT_PLAYWRIGHT_INSTALL}"
DEMO_CAPTURE_EXECUTION_MODE="${DEMO_CAPTURE_EXECUTION_MODE:-$DEFAULT_CAPTURE_MODE}"

json_get() {
  local path="$1"
  python - "$path" <<'PY'
import json
import sys

path = [part for part in sys.argv[1].split(".") if part]
value = json.load(sys.stdin)
for part in path:
    if isinstance(value, list):
        value = value[int(part)]
    elif isinstance(value, dict):
        value = value[part]
    else:
        raise KeyError(part)

if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("null")
elif isinstance(value, (dict, list)):
    print(json.dumps(value, separators=(",", ":")))
else:
    print(value)
PY
}

assert_eq() {
  local expected="$1"
  local actual="$2"
  local message="$3"
  if [[ "$expected" != "$actual" ]]; then
    echo "Assertion failed: $message (expected='$expected', actual='$actual')"
    exit 1
  fi
}

print_compose_diagnostics() {
  docker compose ps || true
  docker compose logs --no-color --tail=200 api worker redis || true
}

wait_for_api() {
  for _ in $(seq 1 60); do
    if curl -fsS "http://localhost:8000/health" >/dev/null; then
      return 0
    fi
    sleep 2
  done
  return 1
}

poll_job_terminal() {
  local job_id="$1"
  local attempts="${2:-240}"
  local job_json=""
  local status=""
  for _ in $(seq 1 "$attempts"); do
    job_json="$(curl -fsS "http://localhost:8000/jobs/${job_id}")"
    status="$(json_get "status" <<<"$job_json")"
    if [[ "$status" == "finished" || "$status" == "failed" ]]; then
      echo "$job_json"
      return 0
    fi
    sleep 1
  done
  echo "$job_json"
  return 1
}

# Create a minimal env file for compose.
# (Do not rely on .env.example because inline comments can become part of values.)
cat > .env <<'ENV'
ZAI_API_KEY=
ZAI_BASE_URL=https://api.z.ai/api/paas/v4/
ZAI_VISION_MODEL=glm-4.6v
ZAI_REWRITE_MODEL=glm-5
TTS_ENDPOINT=
TTS_MODE=chatterbox_tts_json
REDIS_URL=redis://redis:6379/0
RQ_QUEUE=default
DATA_DIR=/data
DEMO_CAPTURE_EXECUTION_MODE=__DEMO_CAPTURE_EXECUTION_MODE__
INSTALL_PLAYWRIGHT=__INSTALL_PLAYWRIGHT__
ENV
sed -i \
  -e "s/__DEMO_CAPTURE_EXECUTION_MODE__/${DEMO_CAPTURE_EXECUTION_MODE}/g" \
  -e "s/__INSTALL_PLAYWRIGHT__/${INSTALL_PLAYWRIGHT}/g" \
  .env

TMP_DIR="$(mktemp -d)"
SAMPLE_MP4="${TMP_DIR}/ci_sample.mp4"

cleanup() {
  docker compose down -v --remove-orphans || true
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "Running CI smoke profile='${SMOKE_PROFILE}' install_playwright='${INSTALL_PLAYWRIGHT}' execution_mode='${DEMO_CAPTURE_EXECUTION_MODE}'"
docker compose build
docker compose up -d redis api worker

if ! wait_for_api; then
  echo "API did not become healthy in time"
  print_compose_diagnostics
  exit 1
fi

HEALTH_DEPS_JSON="$(curl -fsS "http://localhost:8000/health/deps")"
PLAYWRIGHT_OK="$(json_get "playwright.ok" <<<"$HEALTH_DEPS_JSON")"
PLAYWRIGHT_MODE="$(json_get "playwright.execution_mode" <<<"$HEALTH_DEPS_JSON")"
PLAYWRIGHT_REQUIRED="$(json_get "playwright.required" <<<"$HEALTH_DEPS_JSON")"
assert_eq "$DEMO_CAPTURE_EXECUTION_MODE" "$PLAYWRIGHT_MODE" "Playwright execution mode should match configured mode."
assert_eq "$EXPECTED_PLAYWRIGHT_REQUIRED" "$PLAYWRIGHT_REQUIRED" "Playwright required flag should match smoke profile."
assert_eq "$EXPECTED_PLAYWRIGHT_OK" "$PLAYWRIGHT_OK" "Playwright dependency availability should match smoke profile."

# Build a tiny synthetic MP4 using ffmpeg already present in the API container.
docker compose exec -T api ffmpeg -y \
  -f lavfi -i color=c=black:s=320x240:d=2 \
  -f lavfi -i anullsrc=r=48000:cl=stereo \
  -shortest -c:v libx264 -pix_fmt yuv420p -c:a aac \
  /tmp/ci_sample.mp4 >/dev/null 2>&1
docker compose cp api:/tmp/ci_sample.mp4 "$SAMPLE_MP4" >/dev/null

PROJECT_JSON="$(curl -fsS -F "file=@${SAMPLE_MP4}" "http://localhost:8000/projects")"
PROJECT_ID="$(json_get "project_id" <<<"$PROJECT_JSON")"

TIMELINE_IMPORT_BODY="$(python - <<'PY'
import json

timeline = {
    "timeline_version": "1.0",
    "narration_events": [
        {"id": "n1", "start_ms": 0, "end_ms": 1200, "text": "CI smoke narration line"},
    ],
    "action_events": [
        {"id": "a1", "at_ms": 0, "action": "goto", "target": "https://example.com"},
        {"id": "a2", "at_ms": 400, "action": "wait", "args": {"ms": 300}},
    ],
}
body = {
    "content": json.dumps(timeline),
    "import_format": "json",
    "source_name": "ci_timeline.json",
}
print(json.dumps(body))
PY
)"

IMPORT_JSON="$(curl -fsS \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$TIMELINE_IMPORT_BODY" \
  "http://localhost:8000/projects/${PROJECT_ID}/timeline/import")"
assert_eq "1" "$(json_get "narration_event_count" <<<"$IMPORT_JSON")" "Timeline import should include one narration event."
assert_eq "2" "$(json_get "action_event_count" <<<"$IMPORT_JSON")" "Timeline import should include two action events."

VALIDATE_JSON="$(curl -fsS -X POST "http://localhost:8000/projects/${PROJECT_ID}/timeline/actions/validate")"
assert_eq "2" "$(json_get "action_count" <<<"$VALIDATE_JSON")" "Action validation should return the expected action count."

DEMO_QUEUE_JSON="$(curl -fsS -X POST "http://localhost:8000/projects/${PROJECT_ID}/demo/run")"
assert_eq "$DEMO_CAPTURE_EXECUTION_MODE" "$(json_get "execution_mode" <<<"$DEMO_QUEUE_JSON")" "Demo queue response should include configured execution mode."
DEMO_JOB_ID="$(json_get "job_id" <<<"$DEMO_QUEUE_JSON")"

DEMO_FINAL_JSON="$(poll_job_terminal "$DEMO_JOB_ID" 300 || true)"
DEMO_FINAL_STATUS="$(json_get "status" <<<"$DEMO_FINAL_JSON")"
if [[ "$DEMO_FINAL_STATUS" != "finished" ]]; then
  echo "Demo job did not finish successfully: $DEMO_FINAL_JSON"
  print_compose_diagnostics
  exit 1
fi
DEMO_RESULT_MODE="$(json_get "result.mode" <<<"$DEMO_FINAL_JSON")"
assert_eq "$EXPECTED_DEMO_MODE" "$DEMO_RESULT_MODE" "Demo run mode should match smoke profile expectations."

DEMO_RUNS_JSON="$(curl -fsS "http://localhost:8000/projects/${PROJECT_ID}/demo/runs")"
DEMO_RUN_COUNT="$(json_get "run_count" <<<"$DEMO_RUNS_JSON")"
if [[ "$DEMO_RUN_COUNT" -lt 1 ]]; then
  echo "Expected at least one persisted demo run; got run_count=${DEMO_RUN_COUNT}"
  exit 1
fi
assert_eq "$EXPECTED_DEMO_MODE" "$(json_get "runs.0.mode" <<<"$DEMO_RUNS_JSON")" "Latest persisted demo run mode should match expected demo mode."

SETTINGS_JSON="$(curl -fsS \
  -X PATCH \
  -H "Content-Type: application/json" \
  -d "{\"narration_mode\":\"unified\",\"demo_capture_execution_mode\":\"${DEMO_CAPTURE_EXECUTION_MODE}\"}" \
  "http://localhost:8000/projects/${PROJECT_ID}/settings")"
assert_eq "unified" "$(json_get "narration_mode" <<<"$SETTINGS_JSON")" "Project settings should switch narration mode to unified."

RENDER_QUEUE_JSON="$(curl -fsS -X POST "http://localhost:8000/projects/${PROJECT_ID}/render")"
assert_eq "unified" "$(json_get "narration_mode" <<<"$RENDER_QUEUE_JSON")" "Render queue response should report unified narration mode."
RENDER_JOB_ID="$(json_get "job_id" <<<"$RENDER_QUEUE_JSON")"

RENDER_FINAL_JSON="$(poll_job_terminal "$RENDER_JOB_ID" 360 || true)"
RENDER_FINAL_STATUS="$(json_get "status" <<<"$RENDER_FINAL_JSON")"
if [[ "$RENDER_FINAL_STATUS" != "finished" ]]; then
  echo "Render job did not finish successfully: $RENDER_FINAL_JSON"
  print_compose_diagnostics
  exit 1
fi
assert_eq "unified" "$(json_get "result.mode" <<<"$RENDER_FINAL_JSON")" "Unified render job should return unified mode result."

FINAL_MP4_PATH="$(json_get "result.final_mp4" <<<"$RENDER_FINAL_JSON")"
if [[ "$FINAL_MP4_PATH" == "null" || -z "$FINAL_MP4_PATH" ]]; then
  echo "Unified render result did not include final_mp4 path: $RENDER_FINAL_JSON"
  exit 1
fi
if ! docker compose exec -T api test -s "$FINAL_MP4_PATH"; then
  echo "Expected non-empty final MP4 artifact at: $FINAL_MP4_PATH"
  exit 1
fi

echo "CI smoke checks passed (profile=${SMOKE_PROFILE})"
