from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from backend.app.pipeline.unified import run_unified_pipeline
from backend.app.storage import init_project, load_project


class UnifiedPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.project_id = "proj_unified"

        self.project_dir = Path(self.data_dir) / "projects" / self.project_id
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.input_mp4 = self.project_dir / "input.mp4"
        self.input_mp4.write_bytes(b"source-video")

        init_project(
            data_dir=self.data_dir,
            project_id=self.project_id,
            video_rel_path=str(self.input_mp4),
            video_sha256="source-sha",
            duration_ms=5000,
            width=1280,
            height=720,
            fps=30.0,
            has_audio=True,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_prefers_non_empty_raw_demo_video_for_narration_render(self) -> None:
        raw_demo = self.project_dir / "work" / "demo_runs" / "run_1" / "artifacts" / "raw_demo.mp4"
        raw_demo.parent.mkdir(parents=True, exist_ok=True)
        raw_demo.write_bytes(b"demo-video")

        demo_result = {
            "ok": True,
            "raw_demo_mp4": str(raw_demo),
            "mode": "demo_capture_playwright",
            "artifact_summary": {"raw_demo_playable": True},
        }
        render_result = {
            "ok": True,
            "final_mp4": str(self.project_dir / "exports" / "final.mp4"),
            "render_id": "render_test_1",
            "source_video_path": str(raw_demo),
        }
        with (
            patch("backend.app.pipeline.unified.run_demo_capture", return_value=demo_result),
            patch("backend.app.pipeline.unified.run_tts_only_pipeline", return_value=render_result) as run_render,
        ):
            result = run_unified_pipeline(self.project_id, self.data_dir)

        self.assertTrue(result["ok"])
        self.assertEqual("unified", result["mode"])
        self.assertTrue(str(result["demo_run_id"]).startswith("demo_"))
        self.assertEqual("render_test_1", result["render_id"])
        run_render.assert_called_once_with(
            project_id=self.project_id,
            source_video_path=str(raw_demo),
            render_mode="unified",
            render_context={
                "unified_run_id": result["unified_run_id"],
                "demo_run_id": result["demo_run_id"],
                "demo_artifacts_dir": result["demo"].get("artifacts_dir"),
                "demo_raw_demo_mp4": str(raw_demo),
                "demo_execution_mode": result["demo"]["execution_mode"],
                "demo_mode": result["demo"]["mode"],
            },
        )

        proj = load_project(self.data_dir, self.project_id)
        self.assertEqual(1, len(proj["demo"]["runs"]))
        self.assertEqual("demo_capture_playwright", proj["demo"]["runs"][0]["mode"])
        self.assertEqual("render_test_1", proj["demo"]["runs"][0]["correlation"]["render_id"])

    def test_falls_back_to_input_video_when_raw_demo_missing(self) -> None:
        missing_raw_demo = self.project_dir / "work" / "demo_runs" / "run_missing" / "raw_demo.mp4"
        demo_result = {
            "ok": True,
            "raw_demo_mp4": str(missing_raw_demo),
            "mode": "demo_capture_playwright",
            "artifact_summary": {"raw_demo_playable": True},
        }
        render_result = {
            "ok": True,
            "final_mp4": str(self.project_dir / "exports" / "final.mp4"),
            "render_id": "render_test_2",
            "source_video_path": str(self.input_mp4.resolve()),
        }
        with (
            patch("backend.app.pipeline.unified.run_demo_capture", return_value=demo_result),
            patch("backend.app.pipeline.unified.run_tts_only_pipeline", return_value=render_result) as run_render,
        ):
            run_unified_pipeline(self.project_id, self.data_dir)

        run_render.assert_called_once_with(
            project_id=self.project_id,
            source_video_path=str(self.input_mp4.resolve()),
            render_mode="unified",
            render_context={
                "unified_run_id": ANY,
                "demo_run_id": ANY,
                "demo_artifacts_dir": ANY,
                "demo_raw_demo_mp4": str(missing_raw_demo),
                "demo_execution_mode": "playwright_optional",
                "demo_mode": "demo_capture_playwright",
            },
        )

    def test_falls_back_to_input_video_when_raw_demo_not_playable(self) -> None:
        raw_demo = self.project_dir / "work" / "demo_runs" / "run_bad" / "artifacts" / "raw_demo.mp4"
        raw_demo.parent.mkdir(parents=True, exist_ok=True)
        raw_demo.write_bytes(b"not-playable")
        demo_result = {
            "ok": True,
            "raw_demo_mp4": str(raw_demo),
            "mode": "demo_capture_playwright",
            "artifact_summary": {"raw_demo_playable": False},
        }
        render_result = {
            "ok": True,
            "final_mp4": str(self.project_dir / "exports" / "final.mp4"),
            "render_id": "render_test_3",
            "source_video_path": str(self.input_mp4.resolve()),
        }
        with (
            patch("backend.app.pipeline.unified.run_demo_capture", return_value=demo_result),
            patch("backend.app.pipeline.unified.run_tts_only_pipeline", return_value=render_result) as run_render,
        ):
            run_unified_pipeline(self.project_id, self.data_dir)

        run_render.assert_called_once_with(
            project_id=self.project_id,
            source_video_path=str(self.input_mp4.resolve()),
            render_mode="unified",
            render_context={
                "unified_run_id": ANY,
                "demo_run_id": ANY,
                "demo_artifacts_dir": ANY,
                "demo_raw_demo_mp4": str(raw_demo),
                "demo_execution_mode": "playwright_optional",
                "demo_mode": "demo_capture_playwright",
            },
        )


if __name__ == "__main__":
    unittest.main()
