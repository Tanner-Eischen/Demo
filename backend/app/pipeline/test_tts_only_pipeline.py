from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.pipeline.tts_only import run_tts_only_pipeline
from backend.app.storage import MAX_RENDER_HISTORY, init_project, load_project, save_project


def _write_wav(path: Path, duration_ms: int = 700) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 8000
    frames = max(1, int(rate * (duration_ms / 1000.0)))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(rate)
        wav_file.writeframes(b"\x00\x00" * frames)


def _touch_binary(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class TTSOnlyPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.project_id = "proj_tts_only"

        self.settings_patcher = patch(
            "backend.app.pipeline.tts_only.settings",
            SimpleNamespace(data_dir=self.data_dir, tts_mode="chatterbox_tts_json", tts_endpoint=""),
        )
        self.settings_patcher.start()

        project_dir = Path(self.data_dir) / "projects" / self.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        input_mp4 = project_dir / "input.mp4"
        input_mp4.write_bytes(b"video")

        init_project(
            data_dir=self.data_dir,
            project_id=self.project_id,
            video_rel_path=str(input_mp4),
            video_sha256="source-sha",
            duration_ms=6000,
            width=1280,
            height=720,
            fps=30.0,
            has_audio=True,
        )

        proj = load_project(self.data_dir, self.project_id)
        proj["timeline"]["narration_events"] = [
            {
                "id": "n1",
                "start_ms": 0,
                "end_ms": 1000,
                "text": "Open the dashboard",
                "voice_profile_id": "default",
            },
            {
                "id": "n2",
                "start_ms": 1000,
                "end_ms": 2200,
                "text": "Click create report",
                "voice_profile_id": "default",
            },
        ]
        save_project(self.data_dir, self.project_id, proj)

    def tearDown(self) -> None:
        self.settings_patcher.stop()
        self.tmp.cleanup()

    def test_rerender_reuses_cache_and_records_render_history(self) -> None:
        tts_call_count = {"count": 0}

        def fake_tts_or_silence(*, out_path: Path, duration_ms: int, **_: object) -> tuple[str, int]:
            tts_call_count["count"] += 1
            _write_wav(out_path, duration_ms=max(500, min(duration_ms, 1200)))
            return f"sha-{tts_call_count['count']}", max(500, min(duration_ms, 1200))

        def fake_write_srt(segments: list[dict], srt_path: Path) -> None:
            lines = [
                "1",
                "00:00:00,000 --> 00:00:01,000",
                segments[0]["narration"]["selected_text"],
                "",
            ]
            srt_path.write_text("\n".join(lines), encoding="utf-8")

        def fake_write_filter_script(_segments: list[dict], filter_script: Path, total_duration_ms: int) -> None:
            filter_script.write_text(f"# duration_ms={total_duration_ms}\n", encoding="utf-8")

        def fake_mix_narration_wav(_wavs: list[Path], _filter_script: Path, out_path: Path) -> None:
            _touch_binary(out_path, b"wav")

        def fake_mux(_input_mp4: Path, _narration_wav: Path, out_path: Path) -> None:
            _touch_binary(out_path, b"mp4")

        with (
            patch("backend.app.pipeline.tts_only._video_duration_ms", return_value=5000),
            patch("backend.app.pipeline.tts_only.tts_or_silence", side_effect=fake_tts_or_silence),
            patch("backend.app.pipeline.tts_only.probe_audio_duration_ms", return_value=900),
            patch("backend.app.pipeline.tts_only.write_srt", side_effect=fake_write_srt),
            patch("backend.app.pipeline.tts_only.write_filter_script", side_effect=fake_write_filter_script),
            patch("backend.app.pipeline.tts_only.mix_narration_wav", side_effect=fake_mix_narration_wav),
            patch("backend.app.pipeline.tts_only.mux_final_mp4", side_effect=fake_mux),
            patch("backend.app.pipeline.tts_only.attach_srt_mp4", side_effect=fake_mux),
        ):
            first = run_tts_only_pipeline(self.project_id)
            second = run_tts_only_pipeline(self.project_id)

        self.assertEqual(2, first["generated_segments"])
        self.assertEqual(0, first["cache_hits"])
        self.assertEqual(0, second["generated_segments"])
        self.assertEqual(2, second["cache_hits"])
        self.assertEqual(2, tts_call_count["count"])
        self.assertTrue(str(first["render_id"]).startswith("render_"))
        self.assertTrue(str(second["render_id"]).startswith("render_"))

        cache_dir = Path(self.data_dir) / "projects" / self.project_id / "cache" / "tts"
        self.assertEqual(2, len(list(cache_dir.glob("*.wav"))))

        proj = load_project(self.data_dir, self.project_id)
        render_history = proj["renders"]["history"]
        self.assertEqual(2, len(render_history))
        self.assertEqual("tts_only", render_history[-1]["mode"])
        self.assertEqual(2, render_history[-1]["cache_hits"])
        self.assertFalse(render_history[-1]["error_summary"]["has_error"])
        self.assertIsNone(render_history[-1]["correlation"]["demo_run_id"])
        self.assertTrue(Path(proj["exports"]["artifacts"]["final_mp4_path"]).exists())

    def test_unified_render_history_carries_demo_correlation_and_history_is_bounded(self) -> None:
        proj = load_project(self.data_dir, self.project_id)
        proj["renders"]["history"] = [
            {
                "render_id": f"render_old_{idx}",
                "created_at": "2026-02-19T00:00:00+00:00",
                "status": "completed",
                "mode": "tts_only",
            }
            for idx in range(MAX_RENDER_HISTORY + 10)
        ]
        save_project(self.data_dir, self.project_id, proj)

        def fake_tts_or_silence(*, out_path: Path, duration_ms: int, **_: object) -> tuple[str, int]:
            _write_wav(out_path, duration_ms=max(500, min(duration_ms, 1200)))
            return "sha", max(500, min(duration_ms, 1200))

        def fake_write_srt(segments: list[dict], srt_path: Path) -> None:
            srt_path.write_text(segments[0]["narration"]["selected_text"], encoding="utf-8")

        def fake_write_filter_script(_segments: list[dict], filter_script: Path, total_duration_ms: int) -> None:
            filter_script.write_text(f"# duration_ms={total_duration_ms}\n", encoding="utf-8")

        def fake_mix_narration_wav(_wavs: list[Path], _filter_script: Path, out_path: Path) -> None:
            _touch_binary(out_path, b"wav")

        def fake_mux(_input_mp4: Path, _narration_wav: Path, out_path: Path) -> None:
            _touch_binary(out_path, b"mp4")

        with (
            patch("backend.app.pipeline.tts_only._video_duration_ms", return_value=5000),
            patch("backend.app.pipeline.tts_only.tts_or_silence", side_effect=fake_tts_or_silence),
            patch("backend.app.pipeline.tts_only.probe_audio_duration_ms", return_value=900),
            patch("backend.app.pipeline.tts_only.write_srt", side_effect=fake_write_srt),
            patch("backend.app.pipeline.tts_only.write_filter_script", side_effect=fake_write_filter_script),
            patch("backend.app.pipeline.tts_only.mix_narration_wav", side_effect=fake_mix_narration_wav),
            patch("backend.app.pipeline.tts_only.mux_final_mp4", side_effect=fake_mux),
            patch("backend.app.pipeline.tts_only.attach_srt_mp4", side_effect=fake_mux),
        ):
            result = run_tts_only_pipeline(
                self.project_id,
                render_mode="unified",
                render_context={
                    "unified_run_id": "unified_abc",
                    "demo_run_id": "demo_abc",
                    "demo_raw_demo_mp4": "C:/tmp/raw_demo.mp4",
                    "demo_artifacts_dir": "C:/tmp/artifacts",
                },
            )

        self.assertTrue(result["ok"])
        self.assertTrue(str(result["render_id"]).startswith("render_"))
        self.assertEqual("demo_abc", result["correlation"]["demo_run_id"])

        proj = load_project(self.data_dir, self.project_id)
        render_history = proj["renders"]["history"]
        self.assertLessEqual(len(render_history), MAX_RENDER_HISTORY)
        latest = render_history[-1]
        self.assertEqual("unified", latest["mode"])
        self.assertEqual("demo_abc", latest["correlation"]["demo_run_id"])
        self.assertEqual("unified_abc", latest["correlation"]["unified_run_id"])

    def test_pipeline_requires_narration_events(self) -> None:
        proj = load_project(self.data_dir, self.project_id)
        proj["timeline"]["narration_events"] = []
        save_project(self.data_dir, self.project_id, proj)

        with patch("backend.app.pipeline.tts_only._video_duration_ms", return_value=5000):
            with self.assertRaises(RuntimeError) as ctx:
                run_tts_only_pipeline(self.project_id)
        self.assertIn("No narration events available in timeline", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
