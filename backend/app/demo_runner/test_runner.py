from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.demo_runner.models import DemoActionExecution
from backend.app.demo_runner.models import DemoActionEvent
from backend.app.demo_runner.runner import DemoRunner
from backend.app.demo_runner.runner import run_demo_capture


class _FlakyClickPage:
    def __init__(self) -> None:
        self.click_calls = 0

    def click(self, _target: str, timeout: int = 0) -> None:
        self.click_calls += 1
        if self.click_calls == 1:
            raise RuntimeError(f"Timeout {timeout}ms exceeded")

    def screenshot(self, path: str, full_page: bool = True) -> None:
        _ = full_page
        Path(path).write_bytes(b"screenshot")


class _AlwaysTimeoutPage:
    def __init__(self) -> None:
        self.click_calls = 0

    def click(self, _target: str, timeout: int = 0) -> None:
        self.click_calls += 1
        raise RuntimeError(f"Timeout {timeout}ms exceeded")

    def screenshot(self, path: str, full_page: bool = True) -> None:
        _ = full_page
        Path(path).write_bytes(b"screenshot")


class _NonRetryablePage:
    def __init__(self) -> None:
        self.fill_calls = 0

    def fill(self, _target: str, _value: str, timeout: int = 0) -> None:
        _ = timeout
        self.fill_calls += 1
        raise ValueError("selector not found")

    def screenshot(self, path: str, full_page: bool = True) -> None:
        _ = full_page
        Path(path).write_bytes(b"screenshot")


class DemoRunnerExecutionTests(unittest.TestCase):
    def test_run_demo_capture_optional_mode_falls_back_to_dry_run_when_dependencies_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "demo_run"
            timeline = {
                "action_events": [
                    {"id": "a1", "at_ms": 0, "action": "wait", "args": {"ms": 0}},
                    {"id": "a2", "at_ms": 0, "action": "wait", "args": {"ms": 0}},
                ]
            }

            missing_dep_status = {
                "ok": False,
                "python_package_ok": False,
                "browser_ok": False,
                "error": "Playwright Python package unavailable",
            }
            with patch("backend.app.demo_runner.runner.probe_playwright_dependencies", return_value=missing_dep_status):
                result = run_demo_capture(
                    "proj_demo_runner",
                    timeline,
                    run_dir,
                    execution_mode="playwright_optional",
                )

            self.assertTrue(result["ok"])
            self.assertEqual("demo_capture_dry_run", result["mode"])
            self.assertEqual("playwright_optional", result["execution_mode"])
            self.assertEqual(2, result["actions_total"])
            self.assertEqual(2, result["actions_executed"])
            self.assertEqual(2, result["drift_stats"]["count"])
            self.assertTrue(str(result["run_id"]).startswith("demo_"))
            self.assertIn("total_ms", result["stage_timings_ms"])
            self.assertFalse(result["error_summary"]["has_error"])
            self.assertFalse(result["dependency_status"]["ok"])

            logs_path = Path(result["logs_path"])
            raw_demo_path = Path(result["raw_demo_mp4"])
            self.assertTrue(logs_path.exists())
            self.assertTrue(raw_demo_path.exists())
            self.assertTrue(Path(result["artifacts_dir"]).exists())

    def test_run_demo_capture_required_mode_fails_fast_when_dependencies_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "demo_run"
            timeline = {
                "action_events": [
                    {"id": "a1", "at_ms": 0, "action": "wait", "args": {"ms": 0}},
                ]
            }

            missing_dep_status = {
                "ok": False,
                "python_package_ok": False,
                "browser_ok": False,
                "error": "Playwright Python package unavailable",
            }
            with patch("backend.app.demo_runner.runner.probe_playwright_dependencies", return_value=missing_dep_status):
                result = run_demo_capture(
                    "proj_demo_runner_required",
                    timeline,
                    run_dir,
                    execution_mode="playwright_required",
                )

            self.assertFalse(result["ok"])
            self.assertEqual("demo_capture_failed", result["mode"])
            self.assertEqual("playwright_required", result["execution_mode"])
            self.assertEqual(1, result["actions_total"])
            self.assertEqual(0, result["actions_executed"])
            self.assertIn("playwright_required", result["error"])
            self.assertIn("Playwright Python package unavailable", result["error"])
            self.assertTrue(result["error_summary"]["has_error"])
            self.assertEqual(0, result["error_summary"]["failed_actions"])
            self.assertIn("total_ms", result["stage_timings_ms"])
            self.assertFalse(result["dependency_status"]["ok"])
            self.assertIsNone(result["raw_demo_mp4"])

    def test_retryable_error_retries_then_succeeds_with_attempt_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "demo_run"
            runner = DemoRunner(
                project_id="proj_retry_success",
                run_dir=run_dir,
                execution_mode="playwright_optional",
            )
            page = _FlakyClickPage()
            screenshot_dir = run_dir / "artifacts" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            action = DemoActionEvent(
                id="a_retry",
                at_ms=0,
                action="click",
                target="#submit",
                timeout_ms=250,
                retries=1,
                source_index=0,
            )

            execution = runner._execute_action_with_retry(
                page=page,
                action=action,
                actual_at_ms=0,
                drift_ms=0,
                screenshot_dir=screenshot_dir,
            )

            self.assertEqual("ok", execution.status)
            self.assertEqual(2, execution.attempts)
            self.assertEqual(1, execution.retry_count)
            self.assertEqual(2, len(execution.attempt_logs))
            self.assertEqual("error", execution.attempt_logs[0]["status"])
            self.assertEqual("ok", execution.attempt_logs[1]["status"])
            self.assertEqual(2, page.click_calls)
            self.assertEqual("", execution.screenshot_path)

    def test_retry_exhaustion_persists_failure_metadata_and_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "demo_run"
            runner = DemoRunner(
                project_id="proj_retry_fail",
                run_dir=run_dir,
                execution_mode="playwright_optional",
            )
            page = _AlwaysTimeoutPage()
            screenshot_dir = run_dir / "artifacts" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            action = DemoActionEvent(
                id="a_timeout",
                at_ms=0,
                action="click",
                target="#submit",
                timeout_ms=200,
                retries=1,
                source_index=0,
            )

            execution = runner._execute_action_with_retry(
                page=page,
                action=action,
                actual_at_ms=0,
                drift_ms=0,
                screenshot_dir=screenshot_dir,
            )

            self.assertEqual("error", execution.status)
            self.assertEqual("timeout", execution.error_type)
            self.assertEqual(2, execution.attempts)
            self.assertEqual(1, execution.retry_count)
            self.assertEqual(2, len(execution.attempt_logs))
            self.assertTrue(Path(execution.screenshot_path).exists())
            self.assertEqual(2, page.click_calls)

    def test_non_retryable_error_does_not_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "demo_run"
            runner = DemoRunner(
                project_id="proj_non_retry",
                run_dir=run_dir,
                execution_mode="playwright_optional",
            )
            page = _NonRetryablePage()
            screenshot_dir = run_dir / "artifacts" / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            action = DemoActionEvent(
                id="a_non_retry",
                at_ms=0,
                action="fill",
                target="#name",
                args={"value": "A"},
                timeout_ms=300,
                retries=3,
                source_index=0,
            )

            execution = runner._execute_action_with_retry(
                page=page,
                action=action,
                actual_at_ms=0,
                drift_ms=0,
                screenshot_dir=screenshot_dir,
            )

            self.assertEqual("error", execution.status)
            self.assertEqual("action_error", execution.error_type)
            self.assertEqual(1, execution.attempts)
            self.assertEqual(0, execution.retry_count)
            self.assertEqual(1, len(execution.attempt_logs))
            self.assertEqual(1, page.fill_calls)

    def test_playwright_capture_requires_non_empty_playable_raw_demo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "demo_run"
            timeline = {"action_events": [{"id": "a1", "at_ms": 0, "action": "wait", "args": {"ms": 0}}]}

            def _fake_playwright(self: DemoRunner, actions: list[DemoActionEvent], raw_demo_path: Path) -> tuple[bool, str]:
                _ = actions
                raw_demo_path.write_bytes(b"")
                return True, ""

            with (
                patch(
                    "backend.app.demo_runner.runner.probe_playwright_dependencies",
                    return_value={"ok": True, "python_package_ok": True, "browser_ok": True, "error": ""},
                ),
                patch.object(DemoRunner, "_execute_with_playwright", _fake_playwright),
            ):
                result = run_demo_capture(
                    "proj_demo_runner_artifact_quality",
                    timeline,
                    run_dir,
                    execution_mode="playwright_optional",
                )

            self.assertFalse(result["ok"])
            self.assertEqual("demo_capture_failed", result["mode"])
            self.assertIn("non-empty playable raw_demo.mp4", result["error"])
            self.assertFalse(result["artifact_summary"]["raw_demo_playable"])

    def test_failed_playwright_run_records_trace_and_screenshots_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "demo_run"
            timeline = {"action_events": [{"id": "a1", "at_ms": 0, "action": "wait", "args": {"ms": 0}}]}

            def _fake_playwright(self: DemoRunner, actions: list[DemoActionEvent], raw_demo_path: Path) -> tuple[bool, str]:
                _ = actions
                raw_demo_path.write_bytes(b"video-bytes")
                trace = self.artifacts_dir / "trace.zip"
                trace.parent.mkdir(parents=True, exist_ok=True)
                trace.write_bytes(b"trace")
                screenshot = self.artifacts_dir / "screenshots" / "a1.png"
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(b"screenshot")
                self._trace_path = str(trace)
                self._recording_source_path = str(self.artifacts_dir / "recording.webm")
                self._executions.append(
                    DemoActionExecution(
                        action_id="a1",
                        source_index=0,
                        action="click",
                        planned_at_ms=0,
                        actual_at_ms=0,
                        drift_ms=0,
                        timeout_ms=1000,
                        max_retries=1,
                        attempts=1,
                        retry_count=0,
                        status="error",
                        error="boom",
                        error_type="action_error",
                        screenshot_path=str(screenshot),
                    )
                )
                return True, "runtime failure"

            with (
                patch(
                    "backend.app.demo_runner.runner.probe_playwright_dependencies",
                    return_value={"ok": True, "python_package_ok": True, "browser_ok": True, "error": ""},
                ),
                patch.object(DemoRunner, "_execute_with_playwright", _fake_playwright),
                patch.object(
                    DemoRunner,
                    "_probe_raw_demo_artifact",
                    return_value={
                        "raw_demo_path": str(run_dir / "artifacts" / "raw_demo.mp4"),
                        "raw_demo_exists": True,
                        "raw_demo_size_bytes": 10,
                        "raw_demo_duration_ms": 1000,
                        "raw_demo_playable": True,
                        "raw_demo_probe_error": "",
                    },
                ),
            ):
                result = run_demo_capture(
                    "proj_demo_runner_debug_artifacts",
                    timeline,
                    run_dir,
                    execution_mode="playwright_optional",
                )

            self.assertFalse(result["ok"])
            self.assertEqual("demo_capture_failed", result["mode"])
            self.assertTrue(result["debug_artifacts"]["trace_exists"])
            self.assertEqual(1, result["debug_artifacts"]["screenshot_count"])
            self.assertEqual(1, len(result["debug_artifacts"]["screenshot_paths"]))


if __name__ == "__main__":
    unittest.main()
