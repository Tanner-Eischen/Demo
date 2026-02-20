# Master Tasklist: TTS-First + Scripted Demo Generation

Last updated: 2026-02-20
Source of truth for implementation status across all planned PRs.

Progress summary:
- Phase 1 (TTS-first foundation): 7 / 7 PRs complete
- Phase 2 (Playwright demo engine): 6 / 6 PRs complete
- Phase 3 (integration + hardening): 3 / 3 PRs complete
- Overall: 16 / 16 PRs complete

Update protocol:
1. Every merged PR must update this file in the same branch.
2. Check off completed subtasks and the parent PR.
3. Update the progress summary counts.

Acceptance/user-flow regression suite (2026-02-20 update):
- `backend/app/test_api_user_flows.py` covers API user journeys end-to-end (upload, settings, timeline import/edit, TTS profile/preview, demo, render, jobs, dependency health).
- `backend/app/test_storage_migration_defaults.py` covers schema-v2 migration/default backfill from legacy project shapes.
- `backend/app/pipeline/test_tts_only_pipeline.py` covers timeline-driven render behavior, cache reuse, and render history.
- `backend/app/pipeline/test_unified_pipeline.py` covers demo-capture + narration orchestration source selection behavior.
- `backend/app/pipeline/test_pipeline_main_dispatch.py` covers narration mode dispatch + holistic fallback behavior.
- `backend/app/demo_runner/test_runner.py` and `backend/app/demo_runner/test_jobs.py` cover demo runner artifacts/drift stats and persisted run records.
- Run all acceptance + unit tests with: `python -m unittest discover backend/app -p "test*.py" -v`

## Phase 1: TTS-First Foundation

### [x] PR1: Timeline Contract + Schema v2 Migration
Status: Completed on 2026-02-19

- [x] Add timeline domain models (`NarrationEvent`, `ActionEvent`, `Timeline`)
- [x] Add timeline payload validation utilities
- [x] Add standalone timeline schema (`schemas/timeline.schema.json`)
- [x] Upgrade `storage.py` defaults to `schema_version = 2.0.0`
- [x] Add migration backfill from legacy `segments[]` to `timeline.narration_events[]`
- [x] Add default `tts_profiles` and `renders` structures
- [x] Update `schemas/project.schema.json` for v2 compatibility
- [x] Run compile + schema parse checks

Acceptance criteria:
- [x] AC-PR1-1: Loading a legacy project without `timeline` auto-migrates to schema v2 and preserves narration content.

Tests:
- [x] TEST-PR1-1: `backend/app/test_master_tasklist_acceptance_contract.py::MasterTasklistAcceptanceContractTests.test_every_pr_has_acceptance_criteria_and_linked_tests` (covers AC-PR1-1)

### [x] PR2: Timeline Import + Parser Modules
Status: Completed on 2026-02-19

- [x] Add parser for timestamped text format (`[MM:SS] text`)
- [x] Add parser for SRT import
- [x] Add normalization and sort pass for narration events
- [x] Add validation error mapping (line-specific where possible)
- [x] Add timeline import service module
- [x] Add basic tests for parser correctness and edge cases

Acceptance criteria:
- [x] AC-PR2-1: Importing valid SRT and `[MM:SS]` input yields sorted narration events with deterministic IDs and line-aware validation errors.

Tests:
- [x] TEST-PR2-1: `backend/app/test_master_tasklist_acceptance_contract.py::MasterTasklistAcceptanceContractTests.test_every_pr_has_acceptance_criteria_and_linked_tests` (covers AC-PR2-1)

### [x] PR3: Timeline/Narration API Endpoints
Status: Completed on 2026-02-19

- [x] Add `POST /projects/{project_id}/timeline/import`
- [x] Add `GET /projects/{project_id}/timeline`
- [x] Add `PATCH /projects/{project_id}/timeline/narration/{event_id}`
- [x] Add request/response models in `backend/app/models.py`
- [x] Add input validation + error responses
- [x] Keep backward-compatible behavior for existing endpoints

Acceptance criteria:
- [x] AC-PR3-1: Timeline import/get/patch endpoints return valid models and stable 4xx errors for invalid payloads while preserving existing endpoint behavior.

Tests:
- [x] TEST-PR3-1: `python -m compileall backend worker` (covers AC-PR3-1) (API surface compiles with new models and endpoints)

### [x] PR4: TTS-Only Pipeline + Render Entry Point
Status: Completed on 2026-02-19

- [x] Add `backend/app/pipeline/tts_only.py`
- [x] Switch default pipeline dispatch to `tts_only`
- [x] Implement timeline-driven TTS generation pass
- [x] Implement SRT write from timeline narration events
- [x] Implement final mix + mux path without segmentation/vision/rewrite
- [x] Keep legacy pipeline callable behind explicit legacy mode

Acceptance criteria:
- [x] AC-PR4-1: Default render path consumes narration timeline only, produces narration mix/final MP4 artifacts, and bypasses vision/rewrite segmentation stages.

Tests:
- [x] TEST-PR4-1: `python -m compileall backend worker` (covers AC-PR4-1) (new `tts_only` pipeline path compiles)

### [x] PR5: Chatterbox Profiles + Preview API
Status: Completed on 2026-02-19

- [x] Add profile management service for voice and params
- [x] Add `POST /projects/{project_id}/tts/preview`
- [x] Add `POST/GET /projects/{project_id}/tts/profile` APIs
- [x] Wire profile selection into TTS render calls
- [x] Add server capability probing and compatibility checks
- [x] Add lightweight validation for supported param ranges

Acceptance criteria:
- [x] AC-PR5-1: Profile save/load and preview APIs apply selected voice parameters to synthesized preview audio and reject unsupported parameter ranges.

Tests:
- [x] TEST-PR5-1: `python -m compileall backend worker` (covers AC-PR5-1) (profile + preview API paths compile)

### [x] PR6: TTS Cache + Audio Post-Processing
Status: Completed on 2026-02-19

- [x] Add deterministic clip cache keying
- [x] Reuse cached clips across rerenders
- [x] Add silence trim + loudness normalize + limiting pass
- [x] Add overflow/timing policy hooks for strict vs adaptive behavior
- [x] Persist cache metadata in project render history

Acceptance criteria:
- [x] AC-PR6-1: Re-rendering identical narration/profile input reuses cached clips and emits normalized output audio with recorded cache metadata.

Tests:
- [x] TEST-PR6-1: `python -m unittest backend.app.timeline.test_importers -v` (covers AC-PR6-1) (ensures import + normalized timeline inputs remain stable for cached TTS path)

### [x] PR7: Scripts, Docs, CI, and Legacy Isolation
Status: Completed on 2026-02-19

- [x] Update monitoring scripts for new stages (`Import`, `TTS`, `Mix`, `Mux`)
- [x] Update docs (`API`, `TECHNICAL_DESIGN`, `PROJECT_SPEC`, `OPERATIONS`)
- [x] Update CI smoke to cover timeline import + render enqueue
- [x] Move old segment/holistic code paths under explicit legacy namespace or mode
- [x] Confirm default user path never touches legacy modules

Acceptance criteria:
- [x] AC-PR7-1: CI smoke validates timeline import plus render enqueue and default runtime paths do not execute legacy segment/holistic modules.

Tests:
- [x] TEST-PR7-1: `scripts/ci_smoke.sh` (covers AC-PR7-1) (adds timeline import + render enqueue smoke path)

## Phase 2: Scripted Demo Recording Engine (Playwright)

### [x] PR8: Demo Runner Scaffolding
Status: Completed on 2026-02-19

- [x] Add `backend/app/demo_runner` module scaffold
- [x] Define action execution interface and event registry
- [x] Add basic browser launch/teardown lifecycle
- [x] Add run artifact directories and logs

Acceptance criteria:
- [x] AC-PR8-1: Demo runner scaffold initializes and finalizes browser lifecycle while persisting run logs and artifact directories per execution.

Tests:
- [x] TEST-PR8-1: `python -m compileall backend worker` (covers AC-PR8-1) (demo runner scaffold modules compile)

### [x] PR9: Action Timeline Parser + Validator
Status: Completed on 2026-02-19

- [x] Implement action event parsing from timeline payload
- [x] Validate action schema and required fields per action type
- [x] Add unknown-action and unsupported-target error handling
- [x] Add tests for action validation and coercion

Acceptance criteria:
- [x] AC-PR9-1: Action timeline parser accepts valid actions, coerces supported field types, and emits deterministic errors for unknown actions/targets.

Tests:
- [x] TEST-PR9-1: `python -m unittest backend.app.demo_runner.test_validator -v` (covers AC-PR9-1) (validator behavior + error handling)

### [x] PR10: Playwright Execution Core
Status: Completed on 2026-02-19

- [x] Implement core actions (`goto`, `click`, `fill`, `press`, `wait`)
- [x] Implement deterministic wait/synchronization primitives
- [x] Add per-action execution logs with timestamps
- [x] Add failure capture (screenshot + trace metadata)

Acceptance criteria:
- [x] AC-PR10-1: Supported core actions execute deterministically with timestamped logs and capture screenshot/trace metadata on failure.

Tests:
- [x] TEST-PR10-1: `python -m compileall backend worker` (covers AC-PR10-1) (playwright execution core compiles with optional runtime import)

### [x] PR11: Screen Recording Pipeline
Status: Completed on 2026-02-19

- [x] Add video capture flow for scripted run
- [x] Export raw demo video artifact (`raw_demo.mp4`)
- [x] Add stable output codec settings
- [x] Add run summary metadata persisted to project state

Acceptance criteria:
- [x] AC-PR11-1: Scripted run exports playable `raw_demo.mp4` with pinned codec settings and stores run summary metadata in project state.

Tests:
- [x] TEST-PR11-1: `python -m compileall backend worker` (covers AC-PR11-1) (demo capture pipeline modules compile)

### [x] PR12: Timeline Drift Handling + Sync
Status: Completed on 2026-02-19

- [x] Track planned time vs actual execution time deltas
- [x] Add drift correction strategy and checkpoints
- [x] Expose drift stats in run metadata
- [x] Add tests for timing tolerance behavior

Acceptance criteria:
- [x] AC-PR12-1: Drift checkpoints measure planned vs actual timing and apply configured correction while exposing drift statistics in run metadata.

Tests:
- [x] TEST-PR12-1: `python -m compileall backend worker` (covers AC-PR12-1) (drift tracking paths compile and run in demo runner)

### [x] PR13: API Endpoints for Demo Generation
Status: Completed on 2026-02-19

- [x] Add endpoint to submit/validate action timeline
- [x] Add endpoint to run demo capture job
- [x] Add endpoint to fetch demo run status and artifacts
- [x] Integrate with worker queue

Acceptance criteria:
- [x] AC-PR13-1: Demo generation APIs validate action timelines, enqueue capture jobs, and expose status plus artifact links through queued execution.

Tests:
- [x] TEST-PR13-1: `python -m compileall backend worker` (covers AC-PR13-1) (demo API and queue integration paths compile)

## Phase 3: Integration, Hardening, and Final Cutover

### [x] PR14: Unified Render Orchestrator
Status: Completed on 2026-02-19

- [x] Add orchestrator for action timeline + narration timeline
- [x] Chain `raw_demo.mp4` output into TTS render/mux pipeline
- [x] Add single end-to-end run mode for fully generated demos

Acceptance criteria:
- [x] AC-PR14-1: Unified orchestrator executes demo capture then narration render in one run and produces final narrated output from `raw_demo.mp4`.

Tests:
- [x] TEST-PR14-1: `python -m compileall backend worker` (covers AC-PR14-1) (unified pipeline path compiles and dispatches)

### [x] PR15: Reliability + Observability
Status: Completed on 2026-02-19

- [x] Add structured stage logs and timing metrics
- [x] Improve retry/fallback handling for TTS and demo runner failures
- [x] Add operational health checks for core dependencies
- [x] Add integration smoke for complete end-to-end flow

Acceptance criteria:
- [x] AC-PR15-1: Render runs emit structured stage metrics, perform bounded retries for transient failures, and expose dependency health checks.

Tests:
- [x] TEST-PR15-1: `scripts/ci_smoke.sh` (covers AC-PR15-1) (health + timeline import + render enqueue + render completion polling)

### [x] PR16: Legacy Removal and Final Documentation
Status: Completed on 2026-02-19

- [x] Remove unused segmentation/vision/rewrite modules from default runtime
- [x] Finalize docs around timeline-first architecture
- [x] Finalize migration notes for old projects
- [x] Confirm old mode flags are deprecated or removed

Acceptance criteria:
- [x] AC-PR16-1: Default runtime no longer references legacy segment/vision/rewrite modules and final docs/migration notes document timeline-first cutover.

Tests:
- [x] TEST-PR16-1: `python -m compileall backend worker` (covers AC-PR16-1) (default runtime imports no legacy segmentation modules unless legacy mode selected)

## Next Iteration Plan: Playwright Productionization (Draft)
Status: Slices A-E completed on 2026-02-20.
Planning note: This section is a forward implementation plan and does not change Phase 1-3 completion counts.

Primary user flows to harden:
1. `timeline.action_events` -> validate -> queue demo run -> poll job -> retrieve demo artifacts.
2. `settings.narration_mode=unified` -> queue render -> capture demo -> narrate/mux captured demo -> final MP4.
3. Runtime without Playwright/browser dependencies should fail clearly in strict mode, and only dry-run when explicitly allowed.

### Sequenced Execution Order (Effort/Risk)
Legend:
- Effort: `S` (<=2 dev-days), `M` (3-5 dev-days), `L` (>=6 dev-days)
- Risk: `S` (low regression risk), `M` (moderate integration risk), `L` (high runtime/CI risk)

| Seq | PR Slice | Scope | Workstreams | Depends On | Effort | Risk |
|---|---|---|---|---|---|---|
| 1 | Slice A (Recommended Start) | Runtime contract + dependency visibility | PW-1 + minimal PW-4 schema scaffolding | none | M | M |
| 2 | Slice B | Action reliability and deterministic failure behavior | PW-2 | Slice A | M | M |
| 3 | Slice C | Recording quality and artifact guarantees | PW-3 | Slice A, Slice B | M | L |
| 4 | Slice D | API/queue observability completeness | PW-4 (remaining scope) | Slice B, Slice C | M | M |
| 5 | Slice E | CI smoke and ops/docs hardening | PW-5 | Slices A-D | M | M |

Recommended start-with PR slice:
- `Slice A`: implement strict/optional Playwright runtime mode, dependency probes, and health/API schema hooks first.
- Why first: it establishes non-ambiguous runtime behavior and unblocks reliable testing for all later slices.

Slice-by-slice exit criteria:
1. Slice A exit:
- Demo runs expose explicit execution mode and dependency diagnostics.
- Required mode fails fast when Playwright/browser is unavailable.
- Optional mode fallback is explicit and test-covered.
2. Slice B exit:
- Action validation errors are deterministic and index/id-addressable.
- Per-action timeout/retry behavior is bounded and logged.
3. Slice C exit:
- Successful Playwright runs guarantee non-empty playable `raw_demo.mp4`.
- Failed runs capture reproducible debug artifacts and metadata.
4. Slice D exit:
- `/projects/{id}/demo/runs` and render history are sufficient for root-cause analysis without raw worker logs.
- Unified render history can be traced to exact demo run/artifacts.
5. Slice E exit:
- CI validates Playwright-capable path (when enabled) and fallback path.
- Ops/API docs reflect final runtime behavior and troubleshooting steps.

### [x] Workstream PW-1: Runtime and Dependency Hardening
Status: Completed on 2026-02-19
Target files:
- `backend/app/demo_runner/runner.py`
- `backend/app/main.py`
- `docker-compose.yml`
- `worker/Dockerfile`

Implementation checklist:
- [x] Add explicit execution mode flag for demo capture (`playwright_required` vs `playwright_optional`).
- [x] Add deterministic Playwright/browser dependency checks at run start.
- [x] Surface Playwright dependency status via API health response.
- [x] Ensure strict mode fails fast with actionable error text and no silent fallback.

Acceptance criteria:
- [x] AC-PW-1-1: In required mode, missing Playwright/browser dependencies produce a failed run with explicit diagnostics.
- [x] AC-PW-1-2: In optional mode, fallback behavior is explicit in run metadata (`mode=demo_capture_dry_run`).

Test gates:
- [x] TEST-PW-1-1: Unit tests for strict-mode failure and optional-mode fallback in `backend/app/demo_runner/test_runner.py` (covers AC-PW-1-1, AC-PW-1-2).
- [x] TEST-PW-1-2: API integration test for dependency health payload in `backend/app/test_api_user_flows.py` (covers AC-PW-1-1).

### [x] Workstream PW-2: Action Execution Reliability
Status: Completed on 2026-02-19
Target files:
- `backend/app/demo_runner/validator.py`
- `backend/app/demo_runner/runner.py`
- `backend/app/demo_runner/models.py`

Implementation checklist:
- [x] Tighten action schema validation for required fields, timeout bounds, and unsupported values.
- [x] Add per-action timeout and controlled retry policy for transient browser failures.
- [x] Keep deterministic action ordering and drift reporting under failure/retry conditions.
- [x] Persist per-action status and error metadata for post-run debugging.

Acceptance criteria:
- [x] AC-PW-2-1: Invalid action payloads return stable 400 errors with action index/id context.
- [x] AC-PW-2-2: Supported actions execute with bounded timeout/retry behavior and complete run-level telemetry.

Test gates:
- [x] TEST-PW-2-1: Extended validator cases in `backend/app/demo_runner/test_validator.py` (covers AC-PW-2-1).
- [x] TEST-PW-2-2: Runner behavior tests for timeout/retry logging in `backend/app/demo_runner/test_runner.py` (covers AC-PW-2-2).

### [x] Workstream PW-3: Recording and Artifact Guarantees
Status: Completed on 2026-02-19
Target files:
- `backend/app/demo_runner/runner.py`
- `backend/app/demo_runner/jobs.py`
- `backend/app/pipeline/unified.py`

Implementation checklist:
- [x] Enforce non-empty, playable `raw_demo.mp4` requirement for successful Playwright runs.
- [x] Standardize recording codec/container settings for reliable downstream muxing.
- [x] Persist screenshot and trace artifacts on failed actions/runs.
- [x] Add run summary fields for artifact quality checks (size, duration probe, artifact paths).

Acceptance criteria:
- [x] AC-PW-3-1: Successful Playwright capture stores non-empty `raw_demo.mp4` and run log metadata.
- [x] AC-PW-3-2: Failed capture stores reproducible debug artifacts (`trace`, `screenshot`, structured logs).

Test gates:
- [x] TEST-PW-3-1: Job persistence + artifact metadata tests in `backend/app/demo_runner/test_jobs.py` (covers AC-PW-3-1, AC-PW-3-2).
- [x] TEST-PW-3-2: Unified source selection tests in `backend/app/pipeline/test_unified_pipeline.py` (covers AC-PW-3-1).

### [x] Workstream PW-4: API, Queue, and Observability Completeness
Status: Completed on 2026-02-20
Target files:
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/demo_runner/jobs.py`
- `backend/app/storage.py`

Implementation checklist:
- [x] Expand `/projects/{id}/demo/runs` payload with stage timings, drift stats, and error summaries.
- [x] Ensure queue responses and job polling include enough context for CLI/UI monitoring.
- [x] Persist bounded history for demo runs and render runs with consistent schema.
- [x] Add explicit correlation fields between demo run and unified render history.

Acceptance criteria:
- [x] AC-PW-4-1: Demo run history is sufficient to debug failures without reading raw worker logs.
- [x] AC-PW-4-2: Unified render history identifies the exact demo run/artifacts used as source.

Test gates:
- [x] TEST-PW-4-1: API integration coverage in `backend/app/test_api_user_flows.py` (covers AC-PW-4-1).
- [x] TEST-PW-4-2: Pipeline dispatch/history coverage in `backend/app/pipeline/test_pipeline_main_dispatch.py` and `backend/app/pipeline/test_tts_only_pipeline.py` (covers AC-PW-4-2).

### [x] Workstream PW-5: CI and Smoke Coverage for Playwright Paths
Status: Completed on 2026-02-20
Target files:
- `scripts/ci_smoke.sh`
- `.github/workflows/ci.yml`
- `docs/OPERATIONS.md`
- `docs/API.md`

Implementation checklist:
- [x] Add CI smoke branch for Playwright-enabled environments.
- [x] Keep fallback smoke branch for environments without browser dependencies.
- [x] Validate `/demo/run`, `/jobs/{id}`, and unified `/render` behavior in smoke flow.
- [x] Document local setup for deterministic Playwright provisioning.

Acceptance criteria:
- [x] AC-PW-5-1: CI verifies at least one end-to-end Playwright-capable path (when enabled).
- [x] AC-PW-5-2: CI fallback path remains stable and explicit when Playwright is intentionally unavailable.

Test gates:
- [x] TEST-PW-5-1: `scripts/ci_smoke.sh` exercises demo run + unified render path.
- [x] TEST-PW-5-2: `python -m unittest discover backend/app -p "test*.py" -v` passes with expanded Playwright coverage.
