# TECHNICAL_DESIGN — vo-demo-generator (MVP)

## Architecture Overview
Single-user **modular monolith**:
- FastAPI API handles uploads, project management, job orchestration.
- Redis + RQ executes long-running pipeline steps in a worker container.
- Artifacts stored on a shared volume (`./data`).

```
Client (curl / local) -> FastAPI -> Redis Queue -> Worker -> ffmpeg + (Z.ai optional) + (TTS optional)
```

## Data Model
Primary persisted object: `project.json` in `data/projects/<project_id>/project.json`.

Key properties:
- `source.video` metadata + hashes
- `settings` (segmentation, models, narration, tts)
- `timeline` (canonical `narration_events` + `action_events` for future demo automation)
- `tts_profiles` (named voice/parameter presets)
- `renders` (render history and status)
- `demo` (scripted demo capture runs + artifacts)
- `segments[]` each segment includes:
  - start/end ms
  - keyframes
  - vision outputs (raw + parsed)
  - narration history
  - tts attempts and chosen audio path
- `exports.artifacts` (final mp4, srt, mix wav)

Schema lives in `schemas/project.schema.json`.

## Pipeline Steps
Default path is now `tts_only` (timeline-driven narration synthesis).
`unified` mode runs scripted demo capture first, then narration render/mux against captured output.
Legacy `segment` and `holistic` modes remain available for compatibility.
1) Ingest
- Save input MP4
- ffprobe metadata
- sha256 hash

2) Proxy generation
- `ffmpeg` scale + lower fps for analysis

3) Segmentation (baseline)
- Use ffmpeg scene detection on proxy to propose cut points
- Clamp segment lengths between min/max; merge short segments, split long ones

4) Keyframes
- Extract `start` and `end` frames (optionally `peak` later)

5) Vision event extraction (optional)
- If ZAI_API_KEY set, call GLM-4.6V with keyframes + strict JSON schema prompt
- MVP sends keyframes as `data:image/png;base64,...` URLs (no external hosting needed)
- Validate against schema; persist raw payload + raw response
- Project context from `settings.demo_context` is injected in each vision request body as `project_context`.

6) Global narration planning (new)
- After all vision events are collected, send a one-shot planning call for all segments.
- Returns:
  - project-level summary
  - per-segment narrative goal, transition hint, must-include terms
  - preferred candidate index
- Persist planning artifacts:
  - `work/global_narration_plan_payload.json`
  - `work/global_narration_plan_raw.txt`
- Store status+artifacts in `project.json -> planning.narration_global`.

7) Rewrite-to-fit (optional)
- If ZAI_API_KEY set, call GLM-5 with duration + target words + constraints
- Otherwise, heuristic truncation to target words

8) Rewrite-to-fit per segment (context aware)
- Uses `settings.demo_context`, global summary, and per-segment planning guidance.
- Candidate chosen by `preferred_candidate_index` from global planning when valid; fallback to candidate 0.

9) TTS per segment (optional)
- If TTS_ENDPOINT set, call it (two modes supported):
  - chatterbox JSON `/tts`
  - OpenAI-compatible `/v1/audio/speech`
- Otherwise generate silence WAV with exact segment duration

10) Mix safety
- Narration WAVs are trimmed to their segment duration before delay in filter graph:
  - `atrim=end=<segment_len>`
  - `adelay=<start_ms>`
- Final mix is still hard-trimmed to full export duration.

11) Assemble final MP4
- Create narration mix by placing WAVs at `start_ms` (ffmpeg `adelay` + `amix`)
- Mux narration with original video
- Emit SRT using narration lines

## API Surface (MVP)
- `POST /projects` upload MP4 -> returns `{project_id}`
- `GET /projects/{project_id}` -> returns full project JSON
- `POST /projects/{project_id}/run` -> enqueues pipeline -> returns `{job_id}`
- `GET /jobs/{job_id}` -> job status + latest log snippet
- `GET /health` -> basic health check

## Non-functional Requirements
- Idempotent-ish: rerunning pipeline should reuse existing artifacts where safe
- Crash-safe: persist project updates frequently
- Observable: job log per project, basic progress markers

## Open Questions (deferred)
- Better segmentation heuristics (frame-diff energy + OCR-delta)
- UI editor timeline + waveform preview
- Cache and parallelism for AI calls
