from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.pipeline.utils import atomic_write_json, ensure_dir, utc_now_iso
from backend.app.timeline.models import TIMELINE_VERSION

SCHEMA_VERSION = "2.0.0"
MAX_DEMO_RUN_HISTORY = 50
MAX_RENDER_HISTORY = 50


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _history_limit(value: Any, default: int) -> int:
    parsed = _coerce_int(value, default)
    if parsed < 1:
        return default
    return min(parsed, 500)


def _trim_history(records: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    if len(records) <= limit:
        return records
    return records[-limit:]


def _normalize_stage_timings(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, raw in value.items():
        name = str(key).strip()
        if not name:
            continue
        normalized[name] = max(0, _coerce_int(raw, 0))
    return normalized


def _normalize_error_summary(record: dict[str, Any]) -> dict[str, Any]:
    existing = record.get("error_summary")
    summary = dict(existing) if isinstance(existing, dict) else {}

    execution_summary = record.get("execution_summary")
    failed_actions = _coerce_int((execution_summary or {}).get("error"), 0) if isinstance(execution_summary, dict) else 0
    failed_ids: list[str] = []
    error_types: dict[str, int] = {}
    executions = record.get("executions")
    if isinstance(executions, list):
        for entry in executions:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status") or "ok") == "ok":
                continue
            action_id = str(entry.get("action_id") or "").strip()
            if action_id:
                failed_ids.append(action_id)
            error_type = str(entry.get("error_type") or "action_error").strip() or "action_error"
            error_types[error_type] = error_types.get(error_type, 0) + 1

    message = str(summary.get("message") or record.get("error") or "").strip()
    has_error = bool(summary.get("has_error")) or bool(message) or failed_actions > 0

    return {
        "has_error": has_error,
        "message": message,
        "failed_actions": failed_actions,
        "failed_action_ids": failed_ids,
        "error_types": error_types,
    }


def normalize_demo_run_record(
    record: dict[str, Any],
    *,
    run_id_fallback: str | None = None,
) -> dict[str, Any]:
    normalized = dict(record)

    run_id = str(normalized.get("run_id") or "").strip()
    if not run_id:
        run_id = str(run_id_fallback or "").strip()
    if not run_id:
        run_id = f"demo_{utc_now_iso().replace(':', '').replace('-', '')}"
    normalized["run_id"] = run_id

    if "project_id" in normalized:
        normalized["project_id"] = str(normalized.get("project_id") or "").strip()
    normalized["created_at"] = str(normalized.get("created_at") or utc_now_iso())
    normalized["mode"] = str(normalized.get("mode") or "demo_capture_unknown")
    normalized["execution_mode"] = str(normalized.get("execution_mode") or "playwright_optional")
    normalized["actions_total"] = max(0, _coerce_int(normalized.get("actions_total"), 0))
    normalized["actions_executed"] = max(0, _coerce_int(normalized.get("actions_executed"), 0))
    normalized["stage_timings_ms"] = _normalize_stage_timings(normalized.get("stage_timings_ms"))
    normalized["drift_stats"] = dict(normalized.get("drift_stats") or {})
    normalized["execution_summary"] = dict(normalized.get("execution_summary") or {})
    normalized["correlation"] = dict(normalized.get("correlation") or {})
    normalized["error_summary"] = _normalize_error_summary(normalized)
    return normalized


def normalize_render_record(
    record: dict[str, Any],
    *,
    render_id_fallback: str | None = None,
) -> dict[str, Any]:
    normalized = dict(record)

    render_id = str(normalized.get("render_id") or "").strip()
    if not render_id:
        render_id = str(render_id_fallback or "").strip()
    if not render_id:
        render_id = f"render_{utc_now_iso().replace(':', '').replace('-', '')}"
    normalized["render_id"] = render_id
    normalized["created_at"] = str(normalized.get("created_at") or utc_now_iso())
    normalized["mode"] = str(normalized.get("mode") or "tts_only")
    normalized["status"] = str(normalized.get("status") or "completed")
    normalized["stage_timings_ms"] = _normalize_stage_timings(normalized.get("stage_timings_ms"))
    normalized["correlation"] = dict(normalized.get("correlation") or {})
    normalized["error_summary"] = _normalize_error_summary(normalized)
    if normalized["error_summary"].get("has_error"):
        normalized["status"] = str(normalized.get("status") or "failed")
    return normalized


def _default_segmentation_settings() -> dict[str, Any]:
    return {
        "analysis_fps": 10,
        "min_seg_ms": 2000,
        "max_seg_ms": 8000,
        "merge_rule": "merge_short_segments",
        "diff_method": "frame_diff_energy",
        "ocr_delta_enabled": False,
    }


def _default_models_settings() -> dict[str, Any]:
    return {
        "vision": {
            "provider": "zai_openai_compat",
            "base_url": "https://api.z.ai/api/paas/v4/",
            "model": "glm-4.6v",
            "temperature": 0.2,
            "thinking": "enabled",
        },
        "rewrite": {
            "provider": "zai_openai_compat",
            "base_url": "https://api.z.ai/api/paas/v4/",
            "model": "glm-5",
            "temperature": 0.3,
        },
    }


def _default_narration_settings() -> dict[str, Any]:
    return {
        "wps": 2.25,
        "min_words": 4,
        "max_words": 28,
        "style": "present tense, action+result, no filler",
    }


def _default_tts_settings() -> dict[str, Any]:
    return {
        "provider": "chatterbox",
        "endpoint": "",
        "voice_mode": "predefined_voice",
        "predefined_voice_id": "alloy",
        "default_params": {
            "speed_factor": 1.0,
            "temperature": 0.8,
            "exaggeration": 0.5,
            "cfg_weight": 0.5,
            "seed": 123,
            "language_id": "en",
            "output_format": "wav",
        },
    }


def _default_holistic_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "keyframe_density": 1.0,
        "match_confidence_threshold": 0.5,
    }


def _default_demo_capture_execution_mode() -> str:
    return "playwright_optional"


def _default_timeline(
    narration_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "timeline_version": TIMELINE_VERSION,
        "narration_events": narration_events or [],
        "action_events": [],
    }


def _default_renders() -> dict[str, Any]:
    return {"last_render_id": None, "history": []}


def _default_demo_state() -> dict[str, Any]:
    return {"last_run_id": None, "runs": []}


def _default_exports() -> dict[str, Any]:
    return {"artifacts": {}, "ffmpeg": {"commands": []}}


def _default_profile_from_tts_settings(tts_settings: dict[str, Any]) -> dict[str, Any]:
    params = dict(tts_settings.get("default_params") or {})
    profile: dict[str, Any] = {
        "profile_id": "default",
        "display_name": "Default",
        "provider": str(tts_settings.get("provider") or "chatterbox"),
        "voice_mode": str(tts_settings.get("voice_mode") or "predefined_voice"),
        "params": params,
    }
    endpoint = tts_settings.get("endpoint")
    if isinstance(endpoint, str):
        profile["endpoint"] = endpoint
    reference_audio = tts_settings.get("reference_audio_path")
    if isinstance(reference_audio, str) and reference_audio:
        profile["audio_prompt_path"] = reference_audio
    predefined_voice = tts_settings.get("predefined_voice_id")
    if isinstance(predefined_voice, str) and predefined_voice:
        profile["predefined_voice_id"] = predefined_voice
    return profile


def _segments_to_narration_events(segments: Any) -> list[dict[str, Any]]:
    if not isinstance(segments, list):
        return []

    events: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    for idx, segment in enumerate(segments):
        if not isinstance(segment, dict):
            continue

        raw_id = segment.get("id", idx)
        base_id = f"n{raw_id}"
        if base_id in seen_ids:
            seen_ids[base_id] += 1
            event_id = f"{base_id}_{seen_ids[base_id]}"
        else:
            seen_ids[base_id] = 0
            event_id = base_id

        start_ms = _coerce_int(segment.get("start_ms"), 0)
        end_ms = _coerce_int(segment.get("end_ms"), start_ms)
        if end_ms < start_ms:
            end_ms = start_ms

        narration = segment.get("narration")
        if isinstance(narration, dict):
            text = str(narration.get("selected_text") or "")
        else:
            text = ""

        events.append(
            {
                "id": event_id,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": text,
                "voice_profile_id": "default",
                "meta": {
                    "source": "legacy_segment",
                    "source_segment_id": raw_id,
                },
            }
        )

    events.sort(key=lambda item: (item.get("start_ms", 0), item.get("end_ms", 0), item.get("id", "")))
    return events

def project_dir(data_dir: str, project_id: str) -> Path:
    return Path(data_dir) / "projects" / project_id

def project_json_path(data_dir: str, project_id: str) -> Path:
    return project_dir(data_dir, project_id) / "project.json"

def project_log_path(data_dir: str, project_id: str) -> Path:
    return project_dir(data_dir, project_id) / "logs" / "job.log"

def demo_context_md_path(data_dir: str, project_id: str) -> Path:
    return project_dir(data_dir, project_id) / "demo_context.md"

def write_demo_context_md(data_dir: str, project_id: str, text: str) -> None:
    path = demo_context_md_path(data_dir, project_id)
    ensure_dir(path.parent)
    path.write_text(text or "", encoding="utf-8")

def ensure_project_defaults(proj: dict[str, Any], data_dir: str, project_id: str) -> bool:
    changed = False

    current_schema_version = str(proj.get("schema_version") or "")
    if current_schema_version in {"", "1.0.0", "1.1.0", "1.2.0"}:
        proj["schema_version"] = SCHEMA_VERSION
        changed = True

    settings = proj.get("settings")
    if not isinstance(settings, dict):
        settings = {}
        proj["settings"] = settings
        changed = True

    if not isinstance(settings.get("segmentation"), dict):
        settings["segmentation"] = _default_segmentation_settings()
        changed = True

    if not isinstance(settings.get("models"), dict):
        settings["models"] = _default_models_settings()
        changed = True

    if not isinstance(settings.get("narration"), dict):
        settings["narration"] = _default_narration_settings()
        changed = True

    if not isinstance(settings.get("tts"), dict):
        settings["tts"] = _default_tts_settings()
        changed = True

    if "demo_context" not in settings or not isinstance(settings.get("demo_context"), str):
        settings["demo_context"] = ""
        changed = True

    # Add holistic settings if not present
    if "holistic" not in settings or not isinstance(settings.get("holistic"), dict):
        settings["holistic"] = _default_holistic_settings()
        changed = True
    else:
        holistic = settings["holistic"]
        if "keyframe_density" not in holistic:
            holistic["keyframe_density"] = 1.0
            changed = True
        if "match_confidence_threshold" not in holistic:
            holistic["match_confidence_threshold"] = 0.5
            changed = True

    # Add narration_mode setting if not present
    if "narration_mode" not in settings:
        settings["narration_mode"] = "tts_only"
        changed = True

    mode = str(settings.get("demo_capture_execution_mode") or "").strip().lower()
    if mode not in {"playwright_optional", "playwright_required"}:
        settings["demo_capture_execution_mode"] = _default_demo_capture_execution_mode()
        changed = True
    elif settings.get("demo_capture_execution_mode") != mode:
        settings["demo_capture_execution_mode"] = mode
        changed = True

    if "holistic_fallback_to_segment" not in settings:
        settings["holistic_fallback_to_segment"] = True
        changed = True

    if "segments" not in proj or not isinstance(proj.get("segments"), list):
        proj["segments"] = []
        changed = True

    exports = proj.get("exports")
    if not isinstance(exports, dict):
        exports = _default_exports()
        proj["exports"] = exports
        changed = True
    if not isinstance(exports.get("artifacts"), dict):
        exports["artifacts"] = {}
        changed = True
    if not isinstance(exports.get("ffmpeg"), dict):
        exports["ffmpeg"] = {"commands": []}
        changed = True
    if not isinstance(exports["ffmpeg"].get("commands"), list):
        exports["ffmpeg"]["commands"] = []
        changed = True

    planning = proj.get("planning")
    if not isinstance(planning, dict):
        planning = {}
        proj["planning"] = planning
        changed = True

    narration_global = planning.get("narration_global")
    if not isinstance(narration_global, dict):
        planning["narration_global"] = {"status": "not_started"}
        changed = True
    elif "status" not in narration_global:
        narration_global["status"] = "not_started"
        planning["narration_global"] = narration_global
        changed = True

    # Add holistic pipeline state if not present
    if "holistic" not in proj or not isinstance(proj.get("holistic"), dict):
        proj["holistic"] = {"status": "not_started"}
        changed = True

    timeline = proj.get("timeline")
    legacy_narration_events = _segments_to_narration_events(proj.get("segments"))
    if not isinstance(timeline, dict):
        proj["timeline"] = _default_timeline(legacy_narration_events)
        changed = True
    else:
        if timeline.get("timeline_version") != TIMELINE_VERSION:
            timeline["timeline_version"] = TIMELINE_VERSION
            changed = True
        if not isinstance(timeline.get("narration_events"), list):
            timeline["narration_events"] = []
            changed = True
        if not isinstance(timeline.get("action_events"), list):
            timeline["action_events"] = []
            changed = True
        if not timeline.get("narration_events") and legacy_narration_events:
            timeline["narration_events"] = legacy_narration_events
            changed = True

    tts_profiles = proj.get("tts_profiles")
    if not isinstance(tts_profiles, dict):
        tts_profiles = {}
        proj["tts_profiles"] = tts_profiles
        changed = True
    if not isinstance(tts_profiles.get("default"), dict):
        tts_profiles["default"] = _default_profile_from_tts_settings(settings["tts"])
        changed = True
    else:
        default_profile = tts_profiles["default"]
        if not default_profile.get("profile_id"):
            default_profile["profile_id"] = "default"
            changed = True
        if not isinstance(default_profile.get("params"), dict):
            default_profile["params"] = dict(settings["tts"].get("default_params") or {})
            changed = True

    renders = proj.get("renders")
    if not isinstance(renders, dict):
        proj["renders"] = _default_renders()
        changed = True
    else:
        if "last_render_id" not in renders:
            renders["last_render_id"] = None
            changed = True
        if not isinstance(renders.get("history"), list):
            renders["history"] = []
            changed = True
        else:
            render_limit = _history_limit(MAX_RENDER_HISTORY, MAX_RENDER_HISTORY)
            normalized_render_history = [
                normalize_render_record(item)
                for item in renders["history"]
                if isinstance(item, dict)
            ]
            trimmed_render_history = _trim_history(normalized_render_history, limit=render_limit)
            if renders["history"] != trimmed_render_history:
                renders["history"] = trimmed_render_history
                changed = True
            if trimmed_render_history:
                latest_render_id = str(trimmed_render_history[-1].get("render_id") or "")
                if latest_render_id and renders.get("last_render_id") != latest_render_id:
                    renders["last_render_id"] = latest_render_id
                    changed = True

    demo_state = proj.get("demo")
    if not isinstance(demo_state, dict):
        proj["demo"] = _default_demo_state()
        changed = True
    else:
        if "last_run_id" not in demo_state:
            demo_state["last_run_id"] = None
            changed = True
        if not isinstance(demo_state.get("runs"), list):
            demo_state["runs"] = []
            changed = True
        else:
            run_limit = _history_limit(MAX_DEMO_RUN_HISTORY, MAX_DEMO_RUN_HISTORY)
            normalized_demo_runs = [
                normalize_demo_run_record(item)
                for item in demo_state["runs"]
                if isinstance(item, dict)
            ]
            trimmed_demo_runs = _trim_history(normalized_demo_runs, limit=run_limit)
            if demo_state["runs"] != trimmed_demo_runs:
                demo_state["runs"] = trimmed_demo_runs
                changed = True
            if trimmed_demo_runs:
                latest_run_id = str(trimmed_demo_runs[-1].get("run_id") or "")
                if latest_run_id and demo_state.get("last_run_id") != latest_run_id:
                    demo_state["last_run_id"] = latest_run_id
                    changed = True

    # Keep project metadata in sync with canonical settings
    if settings.get("demo_context") is not None:
        write_demo_context_md(data_dir, project_id, settings["demo_context"])

    return changed


def append_demo_run(
    proj: dict[str, Any],
    run_record: dict[str, Any],
    *,
    run_id: str | None = None,
    history_limit: int = MAX_DEMO_RUN_HISTORY,
) -> dict[str, Any]:
    demo_state = proj.get("demo")
    if not isinstance(demo_state, dict):
        demo_state = _default_demo_state()
        proj["demo"] = demo_state

    runs = demo_state.get("runs")
    if not isinstance(runs, list):
        runs = []

    normalized = normalize_demo_run_record(run_record, run_id_fallback=run_id)
    runs.append(normalized)
    runs = _trim_history(runs, limit=_history_limit(history_limit, MAX_DEMO_RUN_HISTORY))
    demo_state["runs"] = runs
    demo_state["last_run_id"] = str(normalized.get("run_id") or demo_state.get("last_run_id"))
    return normalized


def append_render_history(
    proj: dict[str, Any],
    render_record: dict[str, Any],
    *,
    render_id: str | None = None,
    history_limit: int = MAX_RENDER_HISTORY,
) -> dict[str, Any]:
    renders = proj.get("renders")
    if not isinstance(renders, dict):
        renders = _default_renders()
        proj["renders"] = renders

    history = renders.get("history")
    if not isinstance(history, list):
        history = []

    normalized = normalize_render_record(render_record, render_id_fallback=render_id)
    history.append(normalized)
    history = _trim_history(history, limit=_history_limit(history_limit, MAX_RENDER_HISTORY))
    renders["history"] = history
    renders["last_render_id"] = str(normalized.get("render_id") or renders.get("last_render_id"))
    return normalized

def init_project(data_dir: str, project_id: str, video_rel_path: str, video_sha256: str, duration_ms: int,
                 width: int | None, height: int | None, fps: float | None, has_audio: bool) -> dict[str, Any]:
    now = utc_now_iso()
    tts_settings = _default_tts_settings()
    proj = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "created_at": now,
        "updated_at": now,
        "app": {"name": "vo-demo-generator", "version": "0.1.0", "git_commit": "dev"},
        "source": {
            "video": {
                "path": video_rel_path,
                "sha256": video_sha256,
                "duration_ms": duration_ms,
                "width": width,
                "height": height,
                "fps": fps,
                "has_audio": has_audio
            }
        },
        "settings": {
            "segmentation": _default_segmentation_settings(),
            "models": _default_models_settings(),
            "narration": _default_narration_settings(),
            "demo_context": "",
            "tts": tts_settings,
            "holistic": _default_holistic_settings(),
            "narration_mode": "tts_only",
            "demo_capture_execution_mode": _default_demo_capture_execution_mode(),
            "holistic_fallback_to_segment": True,
        },
        "planning": {"narration_global": {"status": "not_started"}},
        "holistic": {"status": "not_started"},
        "timeline": _default_timeline(),
        "tts_profiles": {"default": _default_profile_from_tts_settings(tts_settings)},
        "renders": _default_renders(),
        "demo": _default_demo_state(),
        "segments": [],
        "exports": _default_exports(),
        "compliance": {
            "voice_rights_confirmed": True,
            "notes": "Single-user local tool; user confirms rights/consent.",
        },
    }
    pdir = project_dir(data_dir, project_id)
    ensure_dir(pdir / "work")
    ensure_dir(pdir / "exports")
    ensure_dir(pdir / "logs")
    atomic_write_json(project_json_path(data_dir, project_id), proj)
    write_demo_context_md(data_dir, project_id, "")
    return proj

def load_project(data_dir: str, project_id: str) -> dict[str, Any]:
    path = project_json_path(data_dir, project_id)
    proj = json.loads(path.read_text(encoding="utf-8"))
    ensure_project_defaults(proj, data_dir, project_id)
    return proj

def save_project(data_dir: str, project_id: str, proj: dict[str, Any]) -> None:
    proj["updated_at"] = utc_now_iso()
    atomic_write_json(project_json_path(data_dir, project_id), proj)

def append_log(data_dir: str, project_id: str, line: str) -> None:
    log_path = project_log_path(data_dir, project_id)
    ensure_dir(log_path.parent)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")
