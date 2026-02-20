from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.demo_runner.jobs import run_demo_capture_for_project
from backend.app.storage import MAX_DEMO_RUN_HISTORY, init_project, load_project


class DemoRunnerJobsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.project_id = "proj_demo_job"
        self.project_dir = Path(self.data_dir) / "projects" / self.project_id
        self.project_dir.mkdir(parents=True, exist_ok=True)
        input_mp4 = self.project_dir / "input.mp4"
        input_mp4.write_bytes(b"source")

        init_project(
            data_dir=self.data_dir,
            project_id=self.project_id,
            video_rel_path=str(input_mp4),
            video_sha256="source-sha",
            duration_ms=3000,
            width=640,
            height=360,
            fps=30.0,
            has_audio=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_run_demo_capture_job_persists_run_summary(self) -> None:
        fake_result = {
            "ok": True,
            "project_id": self.project_id,
            "mode": "demo_capture_dry_run",
            "execution_mode": "playwright_optional",
            "raw_demo_mp4": str(self.project_dir / "work" / "demo_runs" / "x" / "artifacts" / "raw_demo.mp4"),
            "actions_total": 0,
            "actions_executed": 0,
            "logs_path": str(self.project_dir / "work" / "demo_runs" / "x" / "logs" / "run.json"),
            "artifacts_dir": str(self.project_dir / "work" / "demo_runs" / "x" / "artifacts"),
            "executions": [],
            "drift_stats": {"count": 0, "mean_ms": 0, "max_ms": 0, "min_ms": 0, "p95_ms": 0},
            "execution_summary": {"total": 0, "ok": 0, "error": 0, "retries": 0, "timeouts": 0},
            "artifact_summary": {
                "raw_demo_path": str(self.project_dir / "work" / "demo_runs" / "x" / "artifacts" / "raw_demo.mp4"),
                "raw_demo_exists": True,
                "raw_demo_size_bytes": 0,
                "raw_demo_duration_ms": 0,
                "raw_demo_playable": False,
            },
            "debug_artifacts": {
                "trace_path": None,
                "trace_exists": False,
                "screenshot_paths": [],
                "screenshot_count": 0,
            },
            "recording_profile": {},
            "dependency_status": {"ok": False},
            "created_at": "2026-02-19T00:00:00+00:00",
        }

        with patch("backend.app.demo_runner.jobs.run_demo_capture", return_value=fake_result):
            result = run_demo_capture_for_project(self.data_dir, self.project_id)

        self.assertTrue(result["ok"])
        self.assertEqual("demo_capture_dry_run", result["mode"])
        self.assertTrue(str(result["run_id"]).startswith("demo_"))
        self.assertEqual(MAX_DEMO_RUN_HISTORY, result["history_limit"])
        self.assertFalse(result["error_summary"]["has_error"])
        proj = load_project(self.data_dir, self.project_id)
        self.assertEqual(1, len(proj["demo"]["runs"]))
        self.assertEqual(result, proj["demo"]["runs"][0])
        self.assertTrue(str(proj["demo"]["last_run_id"]).startswith("demo_"))

        log_path = Path(self.data_dir) / "projects" / self.project_id / "logs" / "job.log"
        self.assertTrue(log_path.exists())
        log_text = log_path.read_text(encoding="utf-8")
        self.assertIn("demo capture start", log_text)
        self.assertIn("demo capture complete", log_text)

    def test_run_demo_capture_job_persists_failed_artifact_metadata(self) -> None:
        trace_path = self.project_dir / "work" / "demo_runs" / "y" / "artifacts" / "trace.zip"
        screenshot_path = self.project_dir / "work" / "demo_runs" / "y" / "artifacts" / "screenshots" / "a1.png"
        fake_result = {
            "ok": False,
            "project_id": self.project_id,
            "mode": "demo_capture_failed",
            "execution_mode": "playwright_optional",
            "raw_demo_mp4": str(self.project_dir / "work" / "demo_runs" / "y" / "artifacts" / "raw_demo.mp4"),
            "actions_total": 1,
            "actions_executed": 1,
            "logs_path": str(self.project_dir / "work" / "demo_runs" / "y" / "logs" / "run.json"),
            "artifacts_dir": str(self.project_dir / "work" / "demo_runs" / "y" / "artifacts"),
            "error": "capture failed",
            "executions": [],
            "drift_stats": {"count": 1, "mean_ms": 0, "max_ms": 0, "min_ms": 0, "p95_ms": 0},
            "execution_summary": {"total": 1, "ok": 0, "error": 1, "retries": 1, "timeouts": 1},
            "artifact_summary": {
                "raw_demo_path": str(self.project_dir / "work" / "demo_runs" / "y" / "artifacts" / "raw_demo.mp4"),
                "raw_demo_exists": True,
                "raw_demo_size_bytes": 1234,
                "raw_demo_duration_ms": 0,
                "raw_demo_playable": False,
                "recording_source_path": str(self.project_dir / "work" / "demo_runs" / "y" / "artifacts" / "video.webm"),
            },
            "debug_artifacts": {
                "trace_path": str(trace_path),
                "trace_exists": True,
                "screenshot_paths": [str(screenshot_path)],
                "screenshot_count": 1,
            },
            "recording_profile": {
                "container": "mp4",
                "video_codec": "libx264",
                "pixel_format": "yuv420p",
            },
            "dependency_status": {"ok": True},
            "created_at": "2026-02-19T00:00:00+00:00",
        }

        with patch("backend.app.demo_runner.jobs.run_demo_capture", return_value=fake_result):
            result = run_demo_capture_for_project(self.data_dir, self.project_id)

        self.assertFalse(result["ok"])
        self.assertEqual("demo_capture_failed", result["mode"])
        self.assertTrue(str(result["run_id"]).startswith("demo_"))
        self.assertTrue(result["error_summary"]["has_error"])
        proj = load_project(self.data_dir, self.project_id)
        self.assertEqual(result, proj["demo"]["runs"][-1])
        self.assertEqual("demo_capture_failed", proj["demo"]["runs"][-1]["mode"])
        self.assertFalse(proj["demo"]["runs"][-1]["artifact_summary"]["raw_demo_playable"])
        self.assertEqual(1, proj["demo"]["runs"][-1]["debug_artifacts"]["screenshot_count"])

        log_path = Path(self.data_dir) / "projects" / self.project_id / "logs" / "job.log"
        log_text = log_path.read_text(encoding="utf-8")
        self.assertIn("demo capture failed", log_text)


if __name__ == "__main__":
    unittest.main()
