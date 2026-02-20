# Migration Notes: Legacy Segment Pipeline -> Timeline-First

Last updated: 2026-02-19

## Overview
The default runtime is now timeline-first and TTS-centric.

- Default `settings.narration_mode`: `tts_only`
- New optional unified mode: `unified` (demo capture + narration render)
- Legacy modes remain opt-in:
  - `legacy_segment` (or `segment`)
  - `legacy_holistic` (or `holistic`)

## Schema Migration
Projects are migrated to `schema_version: 2.0.0` on load.

New canonical fields:
- `timeline`
- `tts_profiles`
- `renders`
- `demo`

Legacy `segments` is preserved for compatibility and auto-converted into
`timeline.narration_events` when timeline data is missing.

## Endpoint Migration
Preferred endpoints:
- `POST /projects/{project_id}/timeline/import`
- `GET /projects/{project_id}/timeline`
- `PATCH /projects/{project_id}/timeline/narration/{event_id}`
- `POST /projects/{project_id}/render`

Backward-compatible alias:
- `POST /projects/{project_id}/run` (delegates to `/render`)

## Operational Notes
- `scripts/ci_smoke.sh` now validates timeline import and render completion.
- `scripts/monitor-pipeline.ps1` supports `tts_only` progress display.

## Deprecation Guidance
Use legacy modes only for regression fallback. New feature work should target:
- timeline import/validation
- TTS profile/preview
- `tts_only` and `unified` render paths
