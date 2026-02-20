from __future__ import annotations

from pathlib import Path
from typing import Any

from rq import get_current_job

from backend.app.config import settings
from backend.app.demo_runner.dependencies import resolve_demo_capture_execution_mode
from backend.app.demo_runner.runner import run_demo_capture
from backend.app.pipeline.tts_only import run_tts_only_pipeline
from backend.app.pipeline.utils import utc_now_iso
from backend.app.storage import MAX_DEMO_RUN_HISTORY, append_demo_run, append_log, load_project, project_dir, save_project


def _queue_name() -> str:
    configured = str(getattr(settings, "rq_queue", "") or "").strip()
    return configured or "default"


def run_unified_pipeline(project_id: str, data_dir: str) -> dict[str, Any]:
    proj = load_project(data_dir, project_id)
    timeline = proj.get("timeline")
    if not isinstance(timeline, dict):
        raise RuntimeError("Timeline missing from project")

    pdir = project_dir(data_dir, project_id)
    unified_run_id = f"unified_{utc_now_iso().replace(':', '').replace('-', '')}"
    demo_run_id = f"demo_{utc_now_iso().replace(':', '').replace('-', '')}"
    run_dir = pdir / "work" / "demo_runs" / demo_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    current_job = get_current_job()
    queue_job_id = str(current_job.id) if current_job and current_job.id else None

    settings_obj = proj.get("settings")
    execution_mode = resolve_demo_capture_execution_mode(
        None,
        project_settings=settings_obj if isinstance(settings_obj, dict) else None,
        default_mode=str(getattr(settings, "demo_capture_execution_mode", "playwright_optional")),
    )

    append_log(data_dir, project_id, f"[{utc_now_iso()}] unified pipeline: demo capture start")
    demo_result = run_demo_capture(
        project_id=project_id,
        timeline=timeline,
        run_dir=run_dir,
        execution_mode=execution_mode,
        run_id=demo_run_id,
        queue_job_id=queue_job_id,
    )
    demo_result["run_id"] = demo_run_id
    demo_result["queue_job_id"] = queue_job_id
    demo_result["history_limit"] = MAX_DEMO_RUN_HISTORY
    correlation = demo_result.get("correlation")
    if not isinstance(correlation, dict):
        correlation = {}
        demo_result["correlation"] = correlation
    correlation["queue_job_id"] = queue_job_id
    correlation["queue_name"] = str(current_job.origin) if current_job and current_job.origin else _queue_name()
    correlation["trigger"] = "unified_pipeline"
    correlation["unified_run_id"] = unified_run_id

    if not bool(demo_result.get("ok")):
        error = str(demo_result.get("error") or "demo capture failed")
        append_log(data_dir, project_id, f"[{utc_now_iso()}] unified pipeline: demo capture failed ({error})")
        raise RuntimeError(error)
    append_log(data_dir, project_id, f"[{utc_now_iso()}] unified pipeline: demo capture done")

    demo_result = append_demo_run(proj, demo_result, run_id=demo_run_id, history_limit=MAX_DEMO_RUN_HISTORY)

    source_video_path = str((pdir / "input.mp4").resolve())
    raw_demo_mp4 = demo_result.get("raw_demo_mp4")
    artifact_summary = demo_result.get("artifact_summary")
    raw_demo_playable: bool | None = None
    if isinstance(artifact_summary, dict) and "raw_demo_playable" in artifact_summary:
        raw_demo_playable = bool(artifact_summary.get("raw_demo_playable"))
    if isinstance(raw_demo_mp4, str):
        candidate = Path(raw_demo_mp4)
        candidate_ok = candidate.exists() and candidate.stat().st_size > 0
        if raw_demo_playable is True and candidate_ok:
            source_video_path = str(candidate)
        elif raw_demo_playable is None and candidate_ok:
            source_video_path = str(candidate)

    save_project(data_dir, project_id, proj)
    append_log(data_dir, project_id, f"[{utc_now_iso()}] unified pipeline: narration render start")
    render_result = run_tts_only_pipeline(
        project_id=project_id,
        source_video_path=source_video_path,
        render_mode="unified",
        render_context={
            "unified_run_id": unified_run_id,
            "demo_run_id": demo_run_id,
            "demo_artifacts_dir": demo_result.get("artifacts_dir"),
            "demo_raw_demo_mp4": demo_result.get("raw_demo_mp4"),
            "demo_execution_mode": demo_result.get("execution_mode"),
            "demo_mode": demo_result.get("mode"),
        },
    )

    # Persist explicit correlation from demo run -> render history record.
    proj_after_render = load_project(data_dir, project_id)
    demo_state_after = proj_after_render.get("demo")
    runs_after = demo_state_after.get("runs") if isinstance(demo_state_after, dict) else None
    if isinstance(runs_after, list):
        for item in reversed(runs_after):
            if not isinstance(item, dict):
                continue
            if str(item.get("run_id") or "") != demo_run_id:
                continue
            item_corr = item.get("correlation")
            if not isinstance(item_corr, dict):
                item_corr = {}
                item["correlation"] = item_corr
            item_corr["render_id"] = render_result.get("render_id")
            item_corr["render_mode"] = render_result.get("mode")
            item_corr["source_video_path"] = render_result.get("source_video_path")
            break
        save_project(data_dir, project_id, proj_after_render)

    append_log(data_dir, project_id, f"[{utc_now_iso()}] unified pipeline complete")
    return {
        "ok": True,
        "project_id": project_id,
        "mode": "unified",
        "unified_run_id": unified_run_id,
        "demo_run_id": demo_run_id,
        "render_id": render_result.get("render_id"),
        "demo": demo_result,
        "render": render_result,
        "final_mp4": render_result.get("final_mp4"),
    }
