# API - vo-demo-generator (MVP)

Base URL: `http://localhost:8000`

## POST /projects
Multipart form upload.
- field: `file` (mp4)

Response:
```json
{ "project_id": "proj_xxx" }
```

## PATCH /projects/{project_id}/settings
Patch mutable project settings.

Request:
```json
{
  "demo_context": "string",
  "demo_capture_execution_mode": "playwright_optional",
  "narration_mode": "unified"
}
```

`narration_mode` supported values:
- `tts_only`
- `timeline`
- `unified`
- `timeline_unified`
- `segment`
- `legacy_segment`
- `holistic`
- `legacy_holistic`

Response:
```json
{
  "project_id": "proj_xxx",
  "demo_context": "string",
  "demo_context_md_path": "path/to/demo_context.md",
  "demo_capture_execution_mode": "playwright_optional",
  "narration_mode": "unified"
}
```

## GET /projects/{project_id}
Returns full `project.json`.

## POST /projects/{project_id}/run
Backward-compatible alias for `/render`.

Response:
```json
{
  "job_id": "rq_job_id",
  "project_id": "proj_xxx",
  "run_type": "render",
  "queue_name": "default",
  "status_url": "/jobs/rq_job_id",
  "queued_at": "2026-02-19T00:00:00+00:00",
  "narration_mode": "tts_only"
}
```

## POST /projects/{project_id}/render
Primary render endpoint.
- Uses current project `settings.narration_mode` (`tts_only` by default).
- In `unified` mode, capture + narration are orchestrated in one render job.

Response:
```json
{
  "job_id": "rq_job_id",
  "project_id": "proj_xxx",
  "run_type": "render",
  "queue_name": "default",
  "status_url": "/jobs/rq_job_id",
  "queued_at": "2026-02-19T00:00:00+00:00",
  "narration_mode": "unified"
}
```

## POST /projects/{project_id}/timeline/import
Import timeline from timestamped txt, SRT, or timeline JSON.

Request:
```json
{
  "content": "[00:00] Intro line",
  "import_format": "auto",
  "source_name": "script.txt"
}
```

Response:
```json
{
  "project_id": "proj_xxx",
  "import_format": "auto",
  "narration_event_count": 10,
  "action_event_count": 0,
  "timeline_version": "1.0"
}
```

## GET /projects/{project_id}/timeline
Returns timeline object (`timeline_version`, `narration_events`, `action_events`).

## PATCH /projects/{project_id}/timeline/narration/{event_id}
Patch one narration event (`start_ms`, `end_ms`, `text`, `voice_profile_id`).

## POST /projects/{project_id}/tts/profile
Upsert a TTS profile for preview/render.

## GET /projects/{project_id}/tts/profile?profile_id=default
Fetch an existing profile.

## POST /projects/{project_id}/tts/preview
Generate a preview WAV for one text line with selected profile/params.

## POST /projects/{project_id}/timeline/actions/validate
Validate `timeline.action_events` against supported action schema.

Supported per-action runtime controls:
- `timeout_ms` (`100-120000`)
- `retries` (`0-3`)

Response:
```json
{
  "project_id": "proj_xxx",
  "action_count": 12
}
```

## POST /projects/{project_id}/demo/run
Queue demo-capture job from `timeline.action_events`.

Response:
```json
{
  "project_id": "proj_xxx",
  "job_id": "rq_job_id",
  "execution_mode": "playwright_optional",
  "run_type": "demo_capture",
  "queue_name": "default",
  "status_url": "/jobs/rq_job_id",
  "queued_at": "2026-02-19T00:00:00+00:00"
}
```

## GET /projects/{project_id}/demo/runs
Returns persisted demo run history for the project.

Run records include:
- `artifact_summary` (size, duration probe, codec/playable checks, artifact paths)
- `debug_artifacts` (trace/screenshot paths and counts)
- `recording_profile` (standardized codec/container settings used for capture output)
- `stage_timings_ms` + `error_summary` + `correlation` for root-cause analysis
- top-level history metadata: `last_run_id`, `run_count`, `history_limit`

## GET /jobs/{job_id}
Returns queued/started/finished/failed job status.

Response:
```json
{
  "job_id": "...",
  "status": "queued|started|finished|failed",
  "result": null,
  "error": null,
  "queue_name": "default",
  "run_type": "render|demo_capture",
  "project_id": "proj_xxx",
  "execution_mode": "playwright_optional",
  "narration_mode": "tts_only|unified|...",
  "queued_at": "2026-02-19T00:00:00+00:00",
  "enqueued_at": "2026-02-19T00:00:00+00:00",
  "started_at": "2026-02-19T00:00:01+00:00",
  "ended_at": "2026-02-19T00:00:10+00:00",
  "func_name": "backend.app.pipeline.pipeline_main.run_pipeline"
}
```

## GET /health
Returns `{ "ok": true }`.

## GET /health/deps
Dependency health for Redis, configured TTS endpoint, and Playwright runtime diagnostics.
