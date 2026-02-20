from __future__ import annotations

from typing import Any

from rq import get_current_job

from backend.app.config import settings
from backend.app.demo_runner.dependencies import resolve_demo_capture_execution_mode
from backend.app.demo_runner.runner import run_demo_capture
from backend.app.pipeline.utils import utc_now_iso
from backend.app.storage import (
    MAX_DEMO_RUN_HISTORY,
    append_demo_run,
    append_log,
    load_project,
    project_dir,
    save_project,
)


def _queue_name() -> str:
    configured = str(getattr(settings, "rq_queue", "") or "").strip()
    return configured or "default"


def run_demo_capture_for_project(
    data_dir: str,
    project_id: str,
    execution_mode: str | None = None,
) -> dict[str, Any]:
    proj = load_project(data_dir, project_id)
    timeline = proj.get("timeline")
    if not isinstance(timeline, dict):
        raise RuntimeError("Timeline missing from project")

    settings_obj = proj.get("settings")
    resolved_mode = resolve_demo_capture_execution_mode(
        execution_mode,
        project_settings=settings_obj if isinstance(settings_obj, dict) else None,
        default_mode=str(getattr(settings, "demo_capture_execution_mode", "playwright_optional")),
    )

    pdir = project_dir(data_dir, project_id)
    run_id = f"demo_{utc_now_iso().replace(':', '').replace('-', '')}"
    run_dir = pdir / "work" / "demo_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    current_job = get_current_job()
    queue_job_id = str(current_job.id) if current_job and current_job.id else None

    append_log(data_dir, project_id, f"[{utc_now_iso()}] demo capture start ({run_id})")
    result = run_demo_capture(
        project_id=project_id,
        timeline=timeline,
        run_dir=run_dir,
        execution_mode=resolved_mode,
        run_id=run_id,
        queue_job_id=queue_job_id,
    )
    result["run_id"] = run_id
    result["queue_job_id"] = queue_job_id
    result["history_limit"] = MAX_DEMO_RUN_HISTORY
    correlation = result.get("correlation")
    if not isinstance(correlation, dict):
        correlation = {}
        result["correlation"] = correlation
    correlation["queue_job_id"] = queue_job_id
    correlation["queue_name"] = str(current_job.origin) if current_job and current_job.origin else _queue_name()
    correlation["trigger"] = "api_demo_run"

    if bool(result.get("ok")):
        append_log(data_dir, project_id, f"[{utc_now_iso()}] demo capture complete ({run_id})")
    else:
        append_log(data_dir, project_id, f"[{utc_now_iso()}] demo capture failed ({run_id})")

    result = append_demo_run(proj, result, run_id=run_id, history_limit=MAX_DEMO_RUN_HISTORY)
    save_project(data_dir, project_id, proj)
    return result
