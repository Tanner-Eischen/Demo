from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.storage import ensure_project_defaults


class StorageMigrationDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_legacy_segments_backfill_timeline_and_defaults(self) -> None:
        project_id = "proj_legacy"
        proj = {
            "schema_version": "1.0.0",
            "settings": {"tts": {"default_params": {"speed_factor": 1.0}}},
            "segments": [
                {
                    "id": 1,
                    "start_ms": 0,
                    "end_ms": 900,
                    "narration": {"selected_text": "Open the dashboard"},
                },
                {
                    "id": 1,
                    "start_ms": 900,
                    "end_ms": 1800,
                    "narration": {"selected_text": "Click reports"},
                },
            ],
        }

        changed = ensure_project_defaults(proj, self.data_dir, project_id)
        self.assertTrue(changed)
        self.assertEqual("2.0.0", proj["schema_version"])
        self.assertEqual("tts_only", proj["settings"]["narration_mode"])
        self.assertEqual("playwright_optional", proj["settings"]["demo_capture_execution_mode"])

        timeline = proj["timeline"]
        self.assertEqual("1.0", timeline["timeline_version"])
        self.assertEqual(2, len(timeline["narration_events"]))
        self.assertEqual("n1", timeline["narration_events"][0]["id"])
        self.assertEqual("n1_1", timeline["narration_events"][1]["id"])
        self.assertEqual("Open the dashboard", timeline["narration_events"][0]["text"])

        self.assertIn("default", proj["tts_profiles"])
        self.assertEqual([], proj["renders"]["history"])
        self.assertEqual([], proj["demo"]["runs"])
        self.assertIsInstance(proj["exports"]["artifacts"], dict)

    def test_existing_timeline_is_not_overwritten_by_legacy_segments(self) -> None:
        project_id = "proj_existing_timeline"
        proj = {
            "schema_version": "2.0.0",
            "settings": {"demo_context": "Keep this", "tts": {"default_params": {}}},
            "timeline": {
                "timeline_version": "1.0",
                "narration_events": [
                    {"id": "n_custom", "start_ms": 0, "end_ms": 1000, "text": "Existing line"}
                ],
                "action_events": [],
            },
            "segments": [
                {
                    "id": 99,
                    "start_ms": 0,
                    "end_ms": 500,
                    "narration": {"selected_text": "Legacy should not replace"},
                }
            ],
        }

        ensure_project_defaults(proj, self.data_dir, project_id)
        narration_events = proj["timeline"]["narration_events"]
        self.assertEqual(1, len(narration_events))
        self.assertEqual("n_custom", narration_events[0]["id"])
        self.assertEqual("Existing line", narration_events[0]["text"])

    def test_demo_context_markdown_synced_from_settings(self) -> None:
        project_id = "proj_context_sync"
        proj = {
            "schema_version": "2.0.0",
            "settings": {"demo_context": "Narration context from settings", "tts": {"default_params": {}}},
            "timeline": {"timeline_version": "1.0", "narration_events": [], "action_events": []},
        }

        ensure_project_defaults(proj, self.data_dir, project_id)
        demo_context_md = Path(self.data_dir) / "projects" / project_id / "demo_context.md"
        self.assertTrue(demo_context_md.exists())
        self.assertEqual("Narration context from settings", demo_context_md.read_text(encoding="utf-8"))
        self.assertEqual("playwright_optional", proj["settings"]["demo_capture_execution_mode"])


if __name__ == "__main__":
    unittest.main()
