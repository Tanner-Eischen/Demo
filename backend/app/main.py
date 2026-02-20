from __future__ import annotations

import secrets

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
import httpx
from fastapi.responses import JSONResponse
from rq.job import Job

from backend.app.config import settings
from backend.app.models import (
    CreateProjectResponse,
    DemoRunQueueResponse,
    DemoRunsResponse,
    HealthDepsResponse,
    JobStatusResponse,
    PatchNarrationEventRequest,
    PatchNarrationEventResponse,
    PatchProjectSettingsRequest,
    PatchProjectSettingsResponse,
    RunProjectResponse,
    TimelineImportRequest,
    TimelineImportResponse,
    TimelineResponse,
    TTSPreviewRequest,
    TTSPreviewResponse,
    TTSProfileResponse,
    UpsertTTSProfileRequest,
    ValidateActionsResponse,
)
from backend.app.demo_runner.dependencies import (
    PLAYWRIGHT_REQUIRED_MODE,
    probe_playwright_dependencies,
    resolve_demo_capture_execution_mode,
)
from backend.app.demo_runner.jobs import run_demo_capture_for_project
from backend.app.demo_runner.validator import DemoActionValidationError, parse_action_events
from backend.app.jobs import get_queue, get_redis
from backend.app.storage import (
    MAX_DEMO_RUN_HISTORY,
    demo_context_md_path,
    init_project,
    load_project,
    project_dir,
    save_project,
    write_demo_context_md,
)
from backend.app.pipeline.tts import tts_or_silence
from backend.app.pipeline.utils import ffprobe_json, sha256_file, utc_now_iso
from backend.app.pipeline.pipeline_main import run_pipeline
from backend.app.timeline.errors import TimelineImportError
from backend.app.timeline.importers import import_narration_timeline
from backend.app.timeline.normalizer import normalize_narration_events
from backend.app.timeline.validator import parse_timeline_payload
from backend.app.tts.cache import build_tts_cache_key, restore_tts_cache, store_tts_cache, tts_cache_path
from backend.app.tts.profiles import (
    ensure_tts_profiles,
    resolve_tts_endpoint,
    resolve_tts_params,
    resolve_tts_profile,
    upsert_tts_profile,
)

app = FastAPI(title="vo-demo-generator", version="0.1.0")


def _get_project_or_404(project_id: str) -> dict:
    try:
        return load_project(settings.data_dir, project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")


def _enqueue_render(project_id: str) -> RunProjectResponse:
    proj = _get_project_or_404(project_id)
    narration_mode = str(((proj.get("settings") or {}).get("narration_mode") or getattr(settings, "narration_mode", "tts_only")))
    queued_at = utc_now_iso()
    q = get_queue()
    job = q.enqueue(
        run_pipeline,
        project_id,
        job_timeout=60 * 60,
        meta={
            "project_id": project_id,
            "run_type": "render",
            "narration_mode": narration_mode,
            "queued_at": queued_at,
        },
    )
    return RunProjectResponse(
        job_id=job.id,
        project_id=project_id,
        run_type="render",
        queue_name=_queue_name(),
        status_url=f"/jobs/{job.id}",
        queued_at=queued_at,
        narration_mode=narration_mode,
    )


def _default_demo_capture_mode() -> str:
    configured_mode = getattr(settings, "demo_capture_execution_mode", "playwright_optional")
    return resolve_demo_capture_execution_mode(None, default_mode=str(configured_mode))


def _project_demo_capture_mode(proj: dict) -> str:
    settings_obj = proj.get("settings")
    return resolve_demo_capture_execution_mode(
        None,
        project_settings=settings_obj if isinstance(settings_obj, dict) else None,
        default_mode=_default_demo_capture_mode(),
    )


def _queue_name() -> str:
    configured = str(getattr(settings, "rq_queue", "") or "").strip()
    return configured or "default"


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return str(value.isoformat())
        except Exception:
            return str(value)
    return str(value)

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/health/deps", response_model=HealthDepsResponse)
def health_deps():
    redis_ok = False
    redis_error = ""
    try:
        redis_ok = bool(get_redis().ping())
    except Exception as exc:
        redis_error = str(exc)

    tts_endpoint = (settings.tts_endpoint or "").strip()
    tts_ok = True
    tts_error = ""
    if tts_endpoint:
        health_url = tts_endpoint
        if health_url.endswith("/tts"):
            health_url = health_url[:-4] + "/health"
        try:
            with httpx.Client(timeout=3) as client:
                resp = client.get(health_url)
                tts_ok = resp.status_code < 500
                if not tts_ok:
                    tts_error = f"status={resp.status_code}"
        except Exception as exc:
            tts_ok = False
            tts_error = str(exc)

    playwright_mode = _default_demo_capture_mode()
    playwright_required = playwright_mode == PLAYWRIGHT_REQUIRED_MODE
    playwright_status = probe_playwright_dependencies()
    playwright_ok = bool(playwright_status.get("ok"))
    playwright_error = str(playwright_status.get("error") or "")

    ok = redis_ok and tts_ok and (playwright_ok if playwright_required else True)
    return {
        "ok": ok,
        "redis": {"ok": redis_ok, "error": redis_error},
        "tts": {"ok": tts_ok, "endpoint": tts_endpoint or None, "error": tts_error},
        "playwright": {
            "ok": playwright_ok,
            "python_package_ok": bool(playwright_status.get("python_package_ok")),
            "browser_ok": bool(playwright_status.get("browser_ok")),
            "error": playwright_error,
            "execution_mode": playwright_mode,
            "required": playwright_required,
        },
    }

@app.post("/projects", response_model=CreateProjectResponse)
async def create_project(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=400, detail="Only .mp4 supported in MVP")

    project_id = f"proj_{secrets.token_hex(4)}"
    pdir = project_dir(settings.data_dir, project_id)
    pdir.mkdir(parents=True, exist_ok=True)

    input_path = pdir / "input.mp4"
    with open(input_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    video_sha = sha256_file(input_path)

    probe = ffprobe_json(input_path)
    # duration in seconds (string)
    duration_s = float(probe.get("format", {}).get("duration") or 0.0)
    duration_ms = int(round(duration_s * 1000))

    # find video stream
    width = height = None
    fps = None
    has_audio = False
    for st in probe.get("streams", []):
        if st.get("codec_type") == "video" and width is None:
            width = st.get("width")
            height = st.get("height")
            afr = st.get("avg_frame_rate")
            if isinstance(afr, str) and "/" in afr:
                num, den = afr.split("/", 1)
                try:
                    fps = float(num) / float(den)
                except Exception:
                    fps = None
        if st.get("codec_type") == "audio":
            has_audio = True

    init_project(
        data_dir=settings.data_dir,
        project_id=project_id,
        video_rel_path=str(input_path),
        video_sha256=video_sha,
        duration_ms=duration_ms,
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio
    )

    # Keep canonical markdown artifact synced with project settings.
    write_demo_context_md(settings.data_dir, project_id, "")

    return CreateProjectResponse(project_id=project_id)

@app.get("/projects/{project_id}")
def get_project(project_id: str):
    proj = _get_project_or_404(project_id)
    return JSONResponse(content=proj)

@app.patch("/projects/{project_id}/settings", response_model=PatchProjectSettingsResponse)
def patch_project_settings(project_id: str, body: PatchProjectSettingsRequest):
    proj = _get_project_or_404(project_id)
    allowed_narration_modes = {
        "tts_only",
        "timeline",
        "unified",
        "timeline_unified",
        "segment",
        "legacy_segment",
        "holistic",
        "legacy_holistic",
    }

    settings_obj = proj.get("settings")
    if not isinstance(settings_obj, dict):
        settings_obj = {}
        proj["settings"] = settings_obj
    if body.demo_context is not None:
        settings_obj["demo_context"] = body.demo_context
        write_demo_context_md(settings.data_dir, project_id, body.demo_context)
    if "demo_context" not in settings_obj or not isinstance(settings_obj.get("demo_context"), str):
        settings_obj["demo_context"] = ""
        write_demo_context_md(settings.data_dir, project_id, "")

    mode = resolve_demo_capture_execution_mode(
        body.demo_capture_execution_mode,
        project_settings=settings_obj,
        default_mode=_default_demo_capture_mode(),
    )
    settings_obj["demo_capture_execution_mode"] = mode
    if body.narration_mode is not None:
        settings_obj["narration_mode"] = body.narration_mode
    narration_mode = str(settings_obj.get("narration_mode") or "tts_only")
    if narration_mode not in allowed_narration_modes:
        narration_mode = "tts_only"
    settings_obj["narration_mode"] = narration_mode

    planning = proj.get("planning")
    if not isinstance(planning, dict):
        planning = {}
        proj["planning"] = planning
    narration_global = planning.get("narration_global")
    if not isinstance(narration_global, dict):
        proj["planning"]["narration_global"] = {"status": "not_started"}
    save_project(settings.data_dir, project_id, proj)

    return PatchProjectSettingsResponse(
        project_id=project_id,
        demo_context=str(settings_obj.get("demo_context") or ""),
        demo_context_md_path=str(demo_context_md_path(settings.data_dir, project_id)),
        demo_capture_execution_mode=mode,
        narration_mode=narration_mode,
    )

@app.post("/projects/{project_id}/timeline/import", response_model=TimelineImportResponse)
def import_timeline(project_id: str, body: TimelineImportRequest):
    proj = _get_project_or_404(project_id)

    source_video = ((proj.get("source") or {}).get("video") or {})
    video_duration_ms = int(source_video.get("duration_ms") or 0)

    try:
        timeline = import_narration_timeline(
            body.content,
            import_format=body.import_format,
            source_name=body.source_name,
            video_duration_ms=video_duration_ms if video_duration_ms > 0 else None,
        )
    except TimelineImportError as exc:
        detail = {"error": str(exc), "code": exc.code, "line_number": exc.line_number}
        raise HTTPException(status_code=400, detail=detail) from exc

    proj["timeline"] = timeline.to_dict()
    settings_obj = proj.get("settings")
    if not isinstance(settings_obj, dict):
        settings_obj = {}
        proj["settings"] = settings_obj
    settings_obj["narration_mode"] = "tts_only"
    save_project(settings.data_dir, project_id, proj)

    return TimelineImportResponse(
        project_id=project_id,
        import_format=body.import_format,
        narration_event_count=len(timeline.narration_events),
        action_event_count=len(timeline.action_events),
        timeline_version=timeline.timeline_version,
    )


@app.get("/projects/{project_id}/timeline", response_model=TimelineResponse)
def get_timeline(project_id: str):
    proj = _get_project_or_404(project_id)
    timeline = proj.get("timeline")
    if not isinstance(timeline, dict):
        timeline = {"timeline_version": "1.0", "narration_events": [], "action_events": []}
    return TimelineResponse(project_id=project_id, timeline=timeline)


@app.patch("/projects/{project_id}/timeline/narration/{event_id}", response_model=PatchNarrationEventResponse)
def patch_narration_event(project_id: str, event_id: str, body: PatchNarrationEventRequest):
    proj = _get_project_or_404(project_id)
    timeline = proj.get("timeline")
    if not isinstance(timeline, dict):
        raise HTTPException(status_code=400, detail="Timeline not initialized for project")

    narration_events = timeline.get("narration_events")
    if not isinstance(narration_events, list):
        raise HTTPException(status_code=400, detail="Timeline narration events are invalid")

    target_event = None
    for item in narration_events:
        if isinstance(item, dict) and str(item.get("id")) == event_id:
            target_event = item
            break
    if target_event is None:
        raise HTTPException(status_code=404, detail=f"Narration event not found: {event_id}")

    updates = body.model_dump(exclude_unset=True)
    if "text" in updates and updates["text"] is not None:
        updates["text"] = str(updates["text"]).strip()
        if not updates["text"]:
            raise HTTPException(status_code=400, detail="Narration text cannot be empty")

    target_event.update({k: v for k, v in updates.items() if v is not None})

    source_video = ((proj.get("source") or {}).get("video") or {})
    video_duration_ms = int(source_video.get("duration_ms") or 0)
    try:
        timeline["narration_events"] = normalize_narration_events(
            [e for e in narration_events if isinstance(e, dict)],
            video_duration_ms=video_duration_ms if video_duration_ms > 0 else None,
        )
        parse_timeline_payload(timeline)
    except (TimelineImportError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    save_project(settings.data_dir, project_id, proj)

    for item in timeline["narration_events"]:
        if str(item.get("id")) == event_id:
            return PatchNarrationEventResponse(project_id=project_id, event=item)

    # Event id may have changed by normalization due to collision resolution.
    return PatchNarrationEventResponse(project_id=project_id, event=timeline["narration_events"][0])


@app.post("/projects/{project_id}/tts/profile", response_model=TTSProfileResponse)
def upsert_profile(project_id: str, body: UpsertTTSProfileRequest):
    proj = _get_project_or_404(project_id)
    try:
        profile = upsert_tts_profile(proj, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    save_project(settings.data_dir, project_id, proj)
    return TTSProfileResponse(project_id=project_id, profile=profile)


@app.get("/projects/{project_id}/tts/profile", response_model=TTSProfileResponse)
def get_profile(project_id: str, profile_id: str = Query(default="default")):
    proj = _get_project_or_404(project_id)
    ensure_tts_profiles(proj)
    try:
        profile = resolve_tts_profile(proj, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TTSProfileResponse(project_id=project_id, profile=profile)


@app.post("/projects/{project_id}/tts/preview", response_model=TTSPreviewResponse)
def tts_preview(project_id: str, body: TTSPreviewRequest):
    proj = _get_project_or_404(project_id)
    ensure_tts_profiles(proj)
    try:
        profile = resolve_tts_profile(proj, body.profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    endpoint = resolve_tts_endpoint(proj, profile, fallback_endpoint=settings.tts_endpoint)
    params = resolve_tts_params(proj, profile, params_override=body.params_override)

    pdir = project_dir(settings.data_dir, project_id)
    preview_dir = pdir / "work" / "previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = pdir / "cache" / "tts_preview"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_key = build_tts_cache_key(
        text=body.text,
        params=params,
        endpoint=endpoint,
        mode=settings.tts_mode,
        audio_prompt_path=params.get("audio_prompt_path"),
        model_signature=f"{settings.tts_mode}:{profile.get('provider', 'chatterbox')}",
    )
    cache_file = tts_cache_path(cache_dir, cache_key)
    out_path = preview_dir / f"preview_{utc_now_iso().replace(':', '').replace('-', '')}.wav"
    cache_hit = restore_tts_cache(cache_file, out_path)
    if cache_hit:
        from backend.app.pipeline.tts import probe_audio_duration_ms

        audio_duration_ms = probe_audio_duration_ms(out_path)
        audio_sha256 = cache_key
    else:
        audio_sha256, audio_duration_ms = tts_or_silence(
            text=body.text,
            out_path=out_path,
            duration_ms=body.duration_ms,
            params=params,
            endpoint=endpoint,
            mode=settings.tts_mode,
            postprocess=True,
        )
        store_tts_cache(out_path, cache_file)

    return TTSPreviewResponse(
        project_id=project_id,
        profile_id=body.profile_id,
        audio_path=str(out_path),
        audio_sha256=audio_sha256,
        audio_duration_ms=int(audio_duration_ms),
        cache_hit=cache_hit,
    )


@app.post("/projects/{project_id}/render", response_model=RunProjectResponse)
def render_project(project_id: str):
    return _enqueue_render(project_id)


@app.post("/projects/{project_id}/run", response_model=RunProjectResponse)
def run_project(project_id: str):
    # Backward-compatible alias for /render.
    return _enqueue_render(project_id)


@app.post("/projects/{project_id}/timeline/actions/validate", response_model=ValidateActionsResponse)
def validate_action_timeline(project_id: str):
    proj = _get_project_or_404(project_id)
    timeline = proj.get("timeline")
    if not isinstance(timeline, dict):
        raise HTTPException(status_code=400, detail="Timeline not initialized for project")
    try:
        actions = parse_action_events(timeline)
    except DemoActionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ValidateActionsResponse(project_id=project_id, action_count=len(actions))


@app.post("/projects/{project_id}/demo/run", response_model=DemoRunQueueResponse)
def run_demo_capture_job(project_id: str):
    proj = _get_project_or_404(project_id)
    execution_mode = _project_demo_capture_mode(proj)
    queued_at = utc_now_iso()
    q = get_queue()
    job = q.enqueue(
        run_demo_capture_for_project,
        settings.data_dir,
        project_id,
        execution_mode,
        job_timeout=60 * 60,
        meta={
            "project_id": project_id,
            "run_type": "demo_capture",
            "execution_mode": execution_mode,
            "queued_at": queued_at,
        },
    )
    return DemoRunQueueResponse(
        project_id=project_id,
        job_id=job.id,
        execution_mode=execution_mode,
        run_type="demo_capture",
        queue_name=_queue_name(),
        status_url=f"/jobs/{job.id}",
        queued_at=queued_at,
    )


@app.get("/projects/{project_id}/demo/runs", response_model=DemoRunsResponse)
def get_demo_runs(project_id: str):
    proj = _get_project_or_404(project_id)
    demo_state = proj.get("demo")
    runs: list[dict] = []
    last_run_id = None
    if isinstance(demo_state, dict):
        if isinstance(demo_state.get("runs"), list):
            runs = [r for r in demo_state["runs"] if isinstance(r, dict)]
        last_run_id = str(demo_state.get("last_run_id")) if demo_state.get("last_run_id") else None
    runs = list(reversed(runs))
    return DemoRunsResponse(
        project_id=project_id,
        last_run_id=last_run_id,
        run_count=len(runs),
        history_limit=MAX_DEMO_RUN_HISTORY,
        runs=runs,
    )

@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str):
    redis = get_redis()
    try:
        job = Job.fetch(job_id, connection=redis)
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")

    status = "queued"
    if job.is_started:
        status = "started"
    if job.is_finished:
        status = "finished"
    if job.is_failed:
        status = "failed"

    err = None
    if job.is_failed:
        err = str(job.exc_info)[-2000:] if job.exc_info else "failed"

    meta = job.meta if isinstance(getattr(job, "meta", None), dict) else {}
    run_type_raw = str(meta.get("run_type")) if meta.get("run_type") else None
    run_type = run_type_raw if run_type_raw in {"render", "demo_capture"} else None
    project_id = str(meta.get("project_id")) if meta.get("project_id") else None
    execution_mode_raw = str(meta.get("execution_mode")) if meta.get("execution_mode") else None
    execution_mode = execution_mode_raw if execution_mode_raw in {"playwright_optional", "playwright_required"} else None
    narration_mode = str(meta.get("narration_mode")) if meta.get("narration_mode") else None
    queued_at = str(meta.get("queued_at")) if meta.get("queued_at") else None
    queue_name = str(getattr(job, "origin", "") or _queue_name())
    enqueued_at = _iso_or_none(getattr(job, "enqueued_at", None))
    started_at = _iso_or_none(getattr(job, "started_at", None))
    ended_at = _iso_or_none(getattr(job, "ended_at", None))
    func_name = str(getattr(job, "func_name", "") or "")

    return JobStatusResponse(
        job_id=job.id,
        status=status,
        result=job.result,
        error=err,
        queue_name=queue_name,
        run_type=run_type,
        project_id=project_id,
        execution_mode=execution_mode,
        narration_mode=narration_mode,
        enqueued_at=enqueued_at,
        started_at=started_at,
        ended_at=ended_at,
        queued_at=queued_at,
        func_name=func_name or None,
    )
