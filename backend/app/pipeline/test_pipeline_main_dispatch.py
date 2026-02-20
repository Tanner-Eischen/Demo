from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.pipeline import pipeline_main


class PipelineMainDispatchTests(unittest.TestCase):
    def test_default_dispatches_to_tts_only(self) -> None:
        with (
            patch("backend.app.pipeline.pipeline_main.load_project", return_value={"settings": {}}),
            patch("backend.app.pipeline.tts_only.run_tts_only_pipeline", return_value={"mode": "tts_only"}) as run_tts,
        ):
            result = pipeline_main.run_pipeline("proj_default")

        self.assertEqual({"mode": "tts_only"}, result)
        run_tts.assert_called_once_with("proj_default")

    def test_unified_mode_dispatches_to_unified_pipeline(self) -> None:
        unified_result = {"mode": "unified", "demo_run_id": "demo_123", "render_id": "render_123"}
        with (
            patch(
                "backend.app.pipeline.pipeline_main.load_project",
                return_value={"settings": {"narration_mode": "unified"}},
            ),
            patch("backend.app.pipeline.pipeline_main.settings", SimpleNamespace(data_dir="C:/tmp/test-data")),
            patch("backend.app.pipeline.unified.run_unified_pipeline", return_value=unified_result) as run_unified,
        ):
            result = pipeline_main.run_pipeline("proj_unified")

        self.assertEqual(unified_result, result)
        self.assertEqual("demo_123", result["demo_run_id"])
        self.assertEqual("render_123", result["render_id"])
        run_unified.assert_called_once_with("proj_unified", "C:/tmp/test-data")

    def test_legacy_segment_mode_dispatches_to_segment_pipeline(self) -> None:
        with (
            patch(
                "backend.app.pipeline.pipeline_main.load_project",
                return_value={"settings": {"narration_mode": "legacy_segment"}},
            ),
            patch("backend.app.pipeline.pipeline_main.run_segment_pipeline", return_value={"mode": "segment"}) as run_seg,
        ):
            result = pipeline_main.run_pipeline("proj_segment")

        self.assertEqual({"mode": "segment"}, result)
        run_seg.assert_called_once_with("proj_segment")

    def test_holistic_failure_falls_back_to_segment_when_enabled(self) -> None:
        with (
            patch(
                "backend.app.pipeline.pipeline_main.load_project",
                return_value={
                    "settings": {
                        "narration_mode": "holistic",
                        "holistic_fallback_to_segment": True,
                    }
                },
            ),
            patch("backend.app.pipeline.pipeline_main.settings", SimpleNamespace(data_dir="C:/tmp/test-data")),
            patch("backend.app.pipeline.holistic.run_holistic_pipeline", side_effect=RuntimeError("boom")),
            patch("backend.app.pipeline.pipeline_main.append_log"),
            patch("backend.app.pipeline.pipeline_main.run_segment_pipeline", return_value={"mode": "segment"}) as run_seg,
        ):
            result = pipeline_main.run_pipeline("proj_holistic")

        self.assertEqual({"mode": "segment"}, result)
        run_seg.assert_called_once_with("proj_holistic")

    def test_unknown_mode_falls_back_to_tts_only(self) -> None:
        with (
            patch(
                "backend.app.pipeline.pipeline_main.load_project",
                return_value={"settings": {"narration_mode": "mystery_mode"}},
            ),
            patch("backend.app.pipeline.tts_only.run_tts_only_pipeline", return_value={"mode": "tts_only"}) as run_tts,
        ):
            result = pipeline_main.run_pipeline("proj_unknown")

        self.assertEqual({"mode": "tts_only"}, result)
        run_tts.assert_called_once_with("proj_unknown")


if __name__ == "__main__":
    unittest.main()
