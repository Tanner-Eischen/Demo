# PROJECT_SPEC — vo-demo-generator

## Problem Statement
Given a UI screen recording (MP4) and an input narration timeline, generate high-quality Chatterbox voiceover audio and export a final MP4 with aligned narration and optional captions, in a reproducible manner.

## Users
- Single user (local-first): the author/creator of UI demos.

## Inputs & Outputs
**Input:** screen recording MP4

**Outputs:**
1. Timeline narration events (timestamped lines)
2. Per-event voiceover WAVs aligned to timeline
3. Final muxed MP4 + optional SRT captions + `project.json` for reproducibility

## MVP Features
- Upload MP4 and create a project
- Automatic segmentation + keyframe extraction
- Per-segment:
  - “what happened” event JSON (vision model, optional)
  - narration rewrite to fit timing (text model, optional)
  - TTS generation (optional; silence fallback)
- Export artifacts: `final.mp4`, `script.srt`, `project.json`

## Success Metrics
- End-to-end run completes for a 2–5 minute demo without manual steps (besides optional narration edits)
- Outputs are reproducible (rerun produces identical deterministic parts given same settings)
- Narration alignment: perceived sync within ~150ms (when TTS is used and timing fit is enabled)

## Constraints
- Local-first, single-user (no auth, no multi-tenant)
- Deterministic segmentation pipeline for consistency
- Long-running tasks must not block HTTP requests (job queue)

## Risks & Mitigations
- **Model JSON drift / invalid JSON** → enforce schema validation and retry; persist raw responses.
- **UI hallucinations** → instructions: “prefer exact on-screen text, low confidence if uncertain.”
- **Voice rights & consent** → store `compliance.voice_rights_confirmed` in project file.
- **TTS timing mismatch** → rewrite loop + optional mild time-stretch within safe bounds.

## Non-goals (MVP)
- Full DAW-style timeline editor
- Multi-speaker / mixing multiple narration tracks
- Lip-sync
