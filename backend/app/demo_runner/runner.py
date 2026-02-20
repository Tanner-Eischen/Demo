from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import Any

from backend.app.demo_runner.dependencies import (
    PLAYWRIGHT_REQUIRED_MODE,
    normalize_demo_capture_execution_mode,
    probe_playwright_dependencies,
)
from backend.app.demo_runner.models import DemoActionEvent, DemoActionExecution, DemoRunResult
from backend.app.demo_runner.validator import parse_action_events
from backend.app.pipeline.utils import ensure_dir, ffprobe_json, run_cmd, utc_now_iso


class DemoRunner:
    """
    Scripted browser demo runner.

    Behavior:
    - If Playwright is available, executes actions with Chromium + video capture.
    - If Playwright is unavailable:
      - `playwright_optional` runs deterministic dry-run fallback.
      - `playwright_required` fails fast with explicit diagnostics.
    """

    def __init__(
        self,
        *,
        project_id: str,
        run_dir: Path,
        execution_mode: str,
        run_id: str = "",
        queue_job_id: str | None = None,
    ):
        self.project_id = project_id
        self.run_dir = run_dir
        self.logs_dir = run_dir / "logs"
        self.artifacts_dir = run_dir / "artifacts"
        self.execution_mode = normalize_demo_capture_execution_mode(execution_mode)
        self.run_id = str(run_id or f"demo_{utc_now_iso().replace(':', '').replace('-', '')}")
        self.queue_job_id = str(queue_job_id) if queue_job_id else None
        ensure_dir(self.logs_dir)
        ensure_dir(self.artifacts_dir)
        self._executions: list[DemoActionExecution] = []
        self._trace_path: str = ""
        self._recording_source_path: str = ""
        self._recording_ffmpeg_cmd: list[str] = []
        self._recording_profile: dict[str, Any] = self._standard_recording_profile()

    def _planned_wait(self, start_ts: float, planned_at_ms: int) -> int:
        planned_at_s = max(0.0, planned_at_ms / 1000.0)
        elapsed = time.monotonic() - start_ts
        remaining = planned_at_s - elapsed
        if remaining > 0:
            time.sleep(remaining)
        return int(round((time.monotonic() - start_ts) * 1000))

    def _log_execution(self, execution: DemoActionExecution) -> None:
        self._executions.append(execution)

    def _drift_stats(self) -> dict[str, Any]:
        drifts = [entry.drift_ms for entry in self._executions]
        if not drifts:
            return {"count": 0, "mean_ms": 0, "max_ms": 0, "min_ms": 0, "p95_ms": 0}
        sorted_drifts = sorted(drifts)
        p95_index = int(round((len(sorted_drifts) - 1) * 0.95))
        return {
            "count": len(drifts),
            "mean_ms": int(round(statistics.mean(drifts))),
            "max_ms": int(max(drifts)),
            "min_ms": int(min(drifts)),
            "p95_ms": int(sorted_drifts[p95_index]),
        }

    def _execution_summary(self) -> dict[str, int]:
        total = len(self._executions)
        ok_count = sum(1 for entry in self._executions if entry.status == "ok")
        error_count = total - ok_count
        retry_count = sum(entry.retry_count for entry in self._executions)
        timeout_count = sum(1 for entry in self._executions if entry.error_type == "timeout")
        return {
            "total": total,
            "ok": ok_count,
            "error": error_count,
            "retries": retry_count,
            "timeouts": timeout_count,
        }

    def _error_summary(
        self,
        *,
        result_error: str,
        dependency_error: str = "",
        runtime_error: str = "",
    ) -> dict[str, Any]:
        failed_entries = [entry for entry in self._executions if entry.status != "ok"]
        failed_action_ids = [entry.action_id for entry in failed_entries if entry.action_id]
        error_types: dict[str, int] = {}
        for entry in failed_entries:
            error_type = str(entry.error_type or "action_error")
            error_types[error_type] = error_types.get(error_type, 0) + 1
        has_error = bool(result_error) or bool(failed_entries)
        return {
            "has_error": has_error,
            "message": result_error,
            "failed_actions": len(failed_entries),
            "failed_action_ids": failed_action_ids,
            "error_types": error_types,
            "dependency_diagnostic": dependency_error,
            "runtime_diagnostic": runtime_error,
        }

    def _standard_recording_profile(self) -> dict[str, Any]:
        return {
            "container": "mp4",
            "video_codec": "libx264",
            "pixel_format": "yuv420p",
            "audio_codec": "aac",
            "video_preset": "veryfast",
            "fps": 30,
            "movflags": "+faststart",
            "width": 1280,
            "height": 720,
        }

    def _collect_screenshot_paths(self) -> list[str]:
        seen: set[str] = set()
        paths: list[str] = []
        for entry in self._executions:
            candidate = str(entry.screenshot_path or "")
            if candidate and candidate not in seen:
                seen.add(candidate)
                paths.append(candidate)
        return paths

    def _probe_raw_demo_artifact(self, raw_demo_path: Path) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "raw_demo_path": str(raw_demo_path),
            "raw_demo_exists": raw_demo_path.exists(),
            "raw_demo_size_bytes": 0,
            "raw_demo_duration_ms": 0,
            "raw_demo_playable": False,
            "raw_demo_video_codec": None,
            "raw_demo_audio_codec": None,
            "raw_demo_probe_error": "",
            "recording_source_path": self._recording_source_path or None,
            "recording_ffmpeg_cmd": list(self._recording_ffmpeg_cmd),
        }
        if not raw_demo_path.exists():
            return summary

        size_bytes = int(raw_demo_path.stat().st_size)
        summary["raw_demo_size_bytes"] = size_bytes
        if size_bytes <= 0:
            return summary

        try:
            probe = ffprobe_json(raw_demo_path)
        except Exception as exc:
            summary["raw_demo_probe_error"] = str(exc)
            return summary

        duration_s = float((probe.get("format") or {}).get("duration") or 0.0)
        duration_ms = int(round(max(duration_s, 0.0) * 1000))
        video_stream = next(
            (stream for stream in (probe.get("streams") or []) if stream.get("codec_type") == "video"),
            None,
        )
        audio_stream = next(
            (stream for stream in (probe.get("streams") or []) if stream.get("codec_type") == "audio"),
            None,
        )

        summary["raw_demo_duration_ms"] = duration_ms
        summary["raw_demo_video_codec"] = (
            str(video_stream.get("codec_name")) if isinstance(video_stream, dict) and video_stream.get("codec_name") else None
        )
        summary["raw_demo_audio_codec"] = (
            str(audio_stream.get("codec_name")) if isinstance(audio_stream, dict) and audio_stream.get("codec_name") else None
        )
        summary["raw_demo_playable"] = bool(video_stream) and duration_ms > 0
        return summary

    def _build_debug_artifacts(self, run_log_path: Path) -> dict[str, Any]:
        screenshot_paths = [path for path in self._collect_screenshot_paths() if Path(path).exists()]
        trace_exists = bool(self._trace_path and Path(self._trace_path).exists())
        source_exists = bool(self._recording_source_path and Path(self._recording_source_path).exists())
        return {
            "trace_path": self._trace_path or None,
            "trace_exists": trace_exists,
            "screenshot_paths": screenshot_paths,
            "screenshot_count": len(screenshot_paths),
            "recording_source_path": self._recording_source_path or None,
            "recording_source_exists": source_exists,
            "run_log_path": str(run_log_path),
        }

    def _transcode_recording_to_mp4(self, source_video_path: Path, raw_demo_path: Path) -> tuple[bool, str]:
        try:
            source_probe = ffprobe_json(source_video_path)
        except Exception as exc:
            return False, f"failed to probe Playwright recording: {exc}"

        has_audio = any(
            isinstance(stream, dict) and stream.get("codec_type") == "audio"
            for stream in (source_probe.get("streams") or [])
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video_path),
            "-c:v",
            str(self._recording_profile["video_codec"]),
            "-preset",
            str(self._recording_profile["video_preset"]),
            "-pix_fmt",
            str(self._recording_profile["pixel_format"]),
            "-movflags",
            str(self._recording_profile["movflags"]),
            "-r",
            str(int(self._recording_profile["fps"])),
        ]
        if has_audio:
            cmd.extend(["-c:a", str(self._recording_profile["audio_codec"]), "-b:a", "128k"])
        else:
            cmd.append("-an")
        cmd.append(str(raw_demo_path))
        self._recording_ffmpeg_cmd = list(cmd)

        code, out, err = run_cmd(cmd)
        if code != 0:
            message = (err or out or "ffmpeg failed").strip()
            return False, f"ffmpeg transcode failed (exit={code}): {message[-500:]}"
        if not raw_demo_path.exists() or raw_demo_path.stat().st_size <= 0:
            return False, "ffmpeg transcode produced empty raw_demo.mp4"
        return True, ""

    def _execute_action(self, page: Any, action: DemoActionEvent, *, timeout_ms: int) -> None:
        if action.action == "goto":
            page.goto(action.target, wait_until="networkidle", timeout=timeout_ms)
        elif action.action == "click":
            page.click(action.target, timeout=timeout_ms)
        elif action.action == "fill":
            page.fill(action.target, str(action.args.get("value", "")), timeout=timeout_ms)
        elif action.action == "press":
            page.press(action.target, str(action.args.get("key", "")), timeout=timeout_ms)
        elif action.action == "wait":
            wait_ms = int(action.args.get("ms") or 0)
            if wait_ms > timeout_ms:
                raise TimeoutError(
                    f"wait action duration {wait_ms}ms exceeds timeout_ms={timeout_ms}"
                )
            if wait_ms > 0:
                page.wait_for_timeout(wait_ms)

    def _classify_error_type(self, error_text: str) -> str:
        lowered = error_text.lower()
        if "timeout" in lowered:
            return "timeout"
        if "target closed" in lowered or "context closed" in lowered or "browser has been closed" in lowered:
            return "transient_browser"
        if "net::" in lowered or "connection reset" in lowered:
            return "transient_network"
        return "action_error"

    def _is_retryable_error(self, error_type: str) -> bool:
        return error_type in {"timeout", "transient_browser", "transient_network"}

    def _execute_action_with_retry(
        self,
        *,
        page: Any,
        action: DemoActionEvent,
        actual_at_ms: int,
        drift_ms: int,
        screenshot_dir: Path,
    ) -> DemoActionExecution:
        max_retries = max(0, int(action.retries))
        max_attempts = 1 + max_retries
        attempt_logs: list[dict[str, Any]] = []
        screenshot_path = ""
        last_error = ""
        last_error_type = ""

        for attempt in range(1, max_attempts + 1):
            attempt_start = time.monotonic()
            try:
                self._execute_action(page, action, timeout_ms=int(action.timeout_ms))
                attempt_elapsed_ms = int(round((time.monotonic() - attempt_start) * 1000))
                attempt_logs.append(
                    {
                        "attempt": attempt,
                        "status": "ok",
                        "elapsed_ms": attempt_elapsed_ms,
                        "retryable": False,
                        "error_type": "",
                        "error": "",
                    }
                )
                return DemoActionExecution(
                    action_id=action.id,
                    source_index=action.source_index,
                    action=action.action,
                    planned_at_ms=int(action.at_ms),
                    actual_at_ms=actual_at_ms,
                    drift_ms=drift_ms,
                    timeout_ms=int(action.timeout_ms),
                    max_retries=max_retries,
                    attempts=attempt,
                    retry_count=attempt - 1,
                    status="ok",
                    attempt_logs=attempt_logs,
                )
            except Exception as exc:  # pragma: no cover - runtime/browser dependent
                attempt_elapsed_ms = int(round((time.monotonic() - attempt_start) * 1000))
                error_text = str(exc)
                error_type = self._classify_error_type(error_text)
                retryable = self._is_retryable_error(error_type)
                will_retry = retryable and attempt < max_attempts
                attempt_logs.append(
                    {
                        "attempt": attempt,
                        "status": "error",
                        "elapsed_ms": attempt_elapsed_ms,
                        "retryable": retryable,
                        "error_type": error_type,
                        "error": error_text,
                    }
                )
                last_error = error_text
                last_error_type = error_type

                if will_retry:
                    continue

                screenshot_file = screenshot_dir / f"{action.id}.png"
                try:
                    page.screenshot(path=str(screenshot_file), full_page=True)
                    screenshot_path = str(screenshot_file)
                except Exception:
                    screenshot_path = ""

                return DemoActionExecution(
                    action_id=action.id,
                    source_index=action.source_index,
                    action=action.action,
                    planned_at_ms=int(action.at_ms),
                    actual_at_ms=actual_at_ms,
                    drift_ms=drift_ms,
                    timeout_ms=int(action.timeout_ms),
                    max_retries=max_retries,
                    attempts=attempt,
                    retry_count=attempt - 1,
                    status="error",
                    error=last_error,
                    error_type=last_error_type,
                    screenshot_path=screenshot_path,
                    attempt_logs=attempt_logs,
                )

        return DemoActionExecution(
            action_id=action.id,
            source_index=action.source_index,
            action=action.action,
            planned_at_ms=int(action.at_ms),
            actual_at_ms=actual_at_ms,
            drift_ms=drift_ms,
            timeout_ms=int(action.timeout_ms),
            max_retries=max(0, int(action.retries)),
            attempts=max_attempts,
            retry_count=max(0, int(action.retries)),
            status="error",
            error=last_error or "unknown action execution failure",
            error_type=last_error_type or "action_error",
            attempt_logs=attempt_logs,
        )

    def _execute_with_playwright(self, actions: list[DemoActionEvent], raw_demo_path: Path) -> tuple[bool, str]:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return False, str(exc)

        screenshot_dir = self.artifacts_dir / "screenshots"
        ensure_dir(screenshot_dir)
        trace_path = self.artifacts_dir / "trace.zip"
        self._trace_path = str(trace_path)
        self._recording_source_path = ""
        self._recording_ffmpeg_cmd = []
        start_ts = time.monotonic()
        playwright_started = False

        try:
            with sync_playwright() as playwright:
                playwright_started = True
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    viewport={
                        "width": int(self._recording_profile["width"]),
                        "height": int(self._recording_profile["height"]),
                    },
                    record_video_dir=str(self.artifacts_dir),
                    record_video_size={
                        "width": int(self._recording_profile["width"]),
                        "height": int(self._recording_profile["height"]),
                    },
                )
                context.tracing.start(screenshots=True, snapshots=True, sources=False)
                page = context.new_page()

                for action in actions:
                    actual_at_ms = self._planned_wait(start_ts, action.at_ms)
                    drift_ms = actual_at_ms - int(action.at_ms)
                    execution = self._execute_action_with_retry(
                        page=page,
                        action=action,
                        actual_at_ms=actual_at_ms,
                        drift_ms=drift_ms,
                        screenshot_dir=screenshot_dir,
                    )
                    self._log_execution(execution)

                try:
                    context.tracing.stop(path=str(trace_path))
                except Exception:
                    pass

                video_source_path = None
                try:
                    if page.video:
                        video_source_path = Path(page.video.path())
                except Exception:
                    video_source_path = None

                try:
                    page.close()
                except Exception:
                    pass
                try:
                    context.close()
                except Exception:
                    pass
                browser.close()

                if video_source_path and video_source_path.exists():
                    self._recording_source_path = str(video_source_path)
                    transcode_ok, transcode_error = self._transcode_recording_to_mp4(video_source_path, raw_demo_path)
                    if not transcode_ok:
                        return True, transcode_error
                else:
                    raw_demo_path.write_bytes(b"")
                    return True, "Playwright recording file missing after run"
        except Exception as exc:  # pragma: no cover - runtime/browser dependent
            return playwright_started, str(exc)
        return True, ""

    def _execute_dry_run(self, actions: list[DemoActionEvent], raw_demo_path: Path) -> None:
        start_ts = time.monotonic()
        for action in actions:
            actual_at_ms = self._planned_wait(start_ts, action.at_ms)
            drift_ms = actual_at_ms - int(action.at_ms)
            self._log_execution(
                DemoActionExecution(
                    action_id=action.id,
                    source_index=action.source_index,
                    action=action.action,
                    planned_at_ms=int(action.at_ms),
                    actual_at_ms=actual_at_ms,
                    drift_ms=drift_ms,
                    timeout_ms=int(action.timeout_ms),
                    max_retries=int(action.retries),
                    attempts=1,
                    retry_count=0,
                    status="ok",
                    attempt_logs=[
                        {
                            "attempt": 1,
                            "status": "ok",
                            "elapsed_ms": 0,
                            "retryable": False,
                            "error_type": "",
                            "error": "",
                        }
                    ],
                )
            )
        raw_demo_path.write_bytes(b"")

    def execute(self, actions: list[DemoActionEvent]) -> DemoRunResult:
        run_log_path = self.logs_dir / "run.json"
        raw_demo_path = self.artifacts_dir / "raw_demo.mp4"
        stage_timings_ms: dict[str, int] = {}
        total_start = time.perf_counter()

        dependency_probe_start = time.perf_counter()
        dependency_status = probe_playwright_dependencies()
        stage_timings_ms["dependency_probe_ms"] = int(round((time.perf_counter() - dependency_probe_start) * 1000))
        dependency_error = str(dependency_status.get("error") or "")
        runtime_error = ""

        used_playwright = False
        if dependency_status.get("ok"):
            capture_start = time.perf_counter()
            used_playwright, runtime_error = self._execute_with_playwright(actions, raw_demo_path)
            stage_timings_ms["capture_ms"] = int(round((time.perf_counter() - capture_start) * 1000))
            if runtime_error:
                dependency_error = runtime_error
                dependency_status = {
                    "ok": False,
                    "python_package_ok": bool(dependency_status.get("python_package_ok")),
                    "browser_ok": False,
                    "error": f"Playwright runtime failure: {runtime_error}",
                }

        if not used_playwright and self.execution_mode == PLAYWRIGHT_REQUIRED_MODE:
            error = (
                "Playwright execution mode is set to 'playwright_required' but dependencies are unavailable. "
                "Either install Playwright+Chromium or switch to 'playwright_optional'. "
                f"Diagnostic: {dependency_error or 'missing dependency probe details'}"
            )
            stage_timings_ms["total_ms"] = int(round((time.perf_counter() - total_start) * 1000))
            error_summary = self._error_summary(
                result_error=error,
                dependency_error=dependency_error,
                runtime_error=runtime_error,
            )
            result = DemoRunResult(
                ok=False,
                project_id=self.project_id,
                mode="demo_capture_failed",
                run_id=self.run_id,
                queue_job_id=self.queue_job_id,
                raw_demo_mp4=None,
                actions_total=len(actions),
                actions_executed=0,
                logs_path=str(run_log_path),
                artifacts_dir=str(self.artifacts_dir),
                error=error,
                executions=self._executions,
                stage_timings_ms=stage_timings_ms,
                drift_stats=self._drift_stats(),
                execution_summary=self._execution_summary(),
                error_summary=error_summary,
                artifact_summary=self._probe_raw_demo_artifact(raw_demo_path),
                debug_artifacts=self._build_debug_artifacts(run_log_path),
                recording_profile=dict(self._recording_profile) if used_playwright else {},
                correlation={"queue_job_id": self.queue_job_id},
                execution_mode=self.execution_mode,
                dependency_status=dependency_status,
            )
            run_log_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            return result

        if not used_playwright:
            dry_run_start = time.perf_counter()
            self._execute_dry_run(actions, raw_demo_path)
            stage_timings_ms["dry_run_ms"] = int(round((time.perf_counter() - dry_run_start) * 1000))

        execution_summary = self._execution_summary()
        artifact_summary = self._probe_raw_demo_artifact(raw_demo_path)
        debug_artifacts = self._build_debug_artifacts(run_log_path)
        failure_reasons: list[str] = []
        if used_playwright:
            if runtime_error:
                failure_reasons.append(f"Playwright runtime failure: {runtime_error}")
            if execution_summary["error"] > 0:
                failure_reasons.append(f"{execution_summary['error']} action(s) failed during capture")
            if execution_summary["error"] == 0 and not bool(artifact_summary.get("raw_demo_playable")):
                probe_error = str(artifact_summary.get("raw_demo_probe_error") or "").strip()
                quality_error = (
                    "Playwright capture did not produce a non-empty playable raw_demo.mp4"
                    if not probe_error
                    else f"Playwright capture did not produce a playable raw_demo.mp4 ({probe_error})"
                )
                failure_reasons.append(quality_error)

        result_ok = not failure_reasons
        result_error = "; ".join(failure_reasons)
        stage_timings_ms["total_ms"] = int(round((time.perf_counter() - total_start) * 1000))
        error_summary = self._error_summary(
            result_error=result_error,
            dependency_error=dependency_error,
            runtime_error=runtime_error,
        )
        result = DemoRunResult(
            ok=result_ok,
            project_id=self.project_id,
            mode=(
                "demo_capture_playwright"
                if used_playwright and result_ok
                else ("demo_capture_failed" if used_playwright else "demo_capture_dry_run")
            ),
            run_id=self.run_id,
            queue_job_id=self.queue_job_id,
            raw_demo_mp4=str(raw_demo_path),
            actions_total=len(actions),
            actions_executed=len(self._executions),
            logs_path=str(run_log_path),
            artifacts_dir=str(self.artifacts_dir),
            error=result_error,
            executions=self._executions,
            stage_timings_ms=stage_timings_ms,
            drift_stats=self._drift_stats(),
            execution_summary=execution_summary,
            error_summary=error_summary,
            artifact_summary=artifact_summary,
            debug_artifacts=debug_artifacts,
            recording_profile=dict(self._recording_profile) if used_playwright else {},
            correlation={"queue_job_id": self.queue_job_id},
            execution_mode=self.execution_mode,
            dependency_status=dependency_status,
        )
        run_log_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return result


def run_demo_capture(
    project_id: str,
    timeline: dict[str, Any],
    run_dir: Path,
    execution_mode: str = "playwright_optional",
    run_id: str = "",
    queue_job_id: str | None = None,
) -> dict[str, Any]:
    actions = parse_action_events(timeline)
    runner = DemoRunner(
        project_id=project_id,
        run_dir=run_dir,
        execution_mode=execution_mode,
        run_id=run_id,
        queue_job_id=queue_job_id,
    )
    result = runner.execute(actions)
    return {
        **result.to_dict(),
        "created_at": utc_now_iso(),
    }
