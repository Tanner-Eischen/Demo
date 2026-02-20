from __future__ import annotations

import tempfile
import unittest
import wave
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.storage import init_project, load_project, save_project


def _write_silent_wav(path: Path, duration_ms: int = 600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_rate = 8000
    frame_count = max(1, int(frame_rate * (duration_ms / 1000.0)))
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


class _FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


class _FakeQueue:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._counter = 0

    def enqueue(self, fn: object, *args: object, **kwargs: object) -> _FakeJob:
        self._counter += 1
        self.calls.append({"fn": fn, "args": args, "kwargs": kwargs})
        return _FakeJob(f"job_{self._counter}")


class ApiUserFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = self.tmp.name
        self.test_settings = SimpleNamespace(
            data_dir=self.data_dir,
            tts_endpoint="",
            tts_mode="chatterbox_tts_json",
            demo_capture_execution_mode="playwright_optional",
        )
        self.settings_patcher = patch("backend.app.main.settings", self.test_settings)
        self.settings_patcher.start()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.settings_patcher.stop()
        self.tmp.cleanup()

    def _init_project(self, project_id: str = "proj_test") -> str:
        pdir = Path(self.data_dir) / "projects" / project_id
        pdir.mkdir(parents=True, exist_ok=True)
        input_mp4 = pdir / "input.mp4"
        input_mp4.write_bytes(b"mp4")
        init_project(
            data_dir=self.data_dir,
            project_id=project_id,
            video_rel_path=str(input_mp4),
            video_sha256="sha256-input",
            duration_ms=5000,
            width=1280,
            height=720,
            fps=30.0,
            has_audio=True,
        )
        return project_id

    def test_create_project_upload_accepts_mp4_and_initializes_state(self) -> None:
        fake_probe = {
            "format": {"duration": "2.5"},
            "streams": [
                {"codec_type": "video", "width": 320, "height": 240, "avg_frame_rate": "30/1"},
                {"codec_type": "audio"},
            ],
        }
        with (
            patch("backend.app.main.secrets.token_hex", return_value="abc12345"),
            patch("backend.app.main.ffprobe_json", return_value=fake_probe),
            patch("backend.app.main.sha256_file", return_value="video-sha"),
        ):
            resp = self.client.post(
                "/projects",
                files={"file": ("sample.mp4", b"fake-video-bytes", "video/mp4")},
            )

        self.assertEqual(200, resp.status_code)
        project_id = resp.json()["project_id"]
        self.assertEqual("proj_abc12345", project_id)

        proj = load_project(self.data_dir, project_id)
        self.assertEqual("2.0.0", proj["schema_version"])
        self.assertEqual(2500, proj["source"]["video"]["duration_ms"])
        self.assertEqual(320, proj["source"]["video"]["width"])
        self.assertTrue((Path(self.data_dir) / "projects" / project_id / "demo_context.md").exists())

    def test_create_project_rejects_non_mp4(self) -> None:
        resp = self.client.post(
            "/projects",
            files={"file": ("sample.mov", b"fake-video-bytes", "video/quicktime")},
        )
        self.assertEqual(400, resp.status_code)
        self.assertEqual("Only .mp4 supported in MVP", resp.json()["detail"])

    def test_project_get_and_settings_patch_flow(self) -> None:
        project_id = self._init_project("proj_settings")
        get_before = self.client.get(f"/projects/{project_id}")
        self.assertEqual(200, get_before.status_code)
        self.assertEqual(project_id, get_before.json()["project_id"])

        patch_resp = self.client.patch(
            f"/projects/{project_id}/settings",
            json={
                "demo_context": "Focus on onboarding and report creation flows.",
                "demo_capture_execution_mode": "playwright_required",
                "narration_mode": "unified",
            },
        )
        self.assertEqual(200, patch_resp.status_code)
        body = patch_resp.json()
        self.assertEqual(project_id, body["project_id"])
        self.assertIn("demo_context.md", body["demo_context_md_path"])
        self.assertEqual("playwright_required", body["demo_capture_execution_mode"])
        self.assertEqual("unified", body["narration_mode"])

        proj = load_project(self.data_dir, project_id)
        self.assertEqual("Focus on onboarding and report creation flows.", proj["settings"]["demo_context"])
        self.assertEqual("playwright_required", proj["settings"]["demo_capture_execution_mode"])
        self.assertEqual("unified", proj["settings"]["narration_mode"])
        self.assertEqual("not_started", proj["planning"]["narration_global"]["status"])

    def test_health_endpoint(self) -> None:
        resp = self.client.get("/health")
        self.assertEqual(200, resp.status_code)
        self.assertEqual({"ok": True}, resp.json())

    def test_timeline_import_get_and_patch_flow(self) -> None:
        project_id = self._init_project("proj_timeline")
        import_resp = self.client.post(
            f"/projects/{project_id}/timeline/import",
            json={
                "content": "[00:02] second line\n[00:00] first line",
                "import_format": "timestamped_txt",
                "source_name": "script.txt",
            },
        )
        self.assertEqual(200, import_resp.status_code)
        self.assertEqual(2, import_resp.json()["narration_event_count"])

        timeline_resp = self.client.get(f"/projects/{project_id}/timeline")
        self.assertEqual(200, timeline_resp.status_code)
        narration_events = timeline_resp.json()["timeline"]["narration_events"]
        self.assertEqual(2, len(narration_events))
        self.assertEqual(0, narration_events[0]["start_ms"])
        self.assertEqual("first line", narration_events[0]["text"])

        event_id = narration_events[0]["id"]
        patch_resp = self.client.patch(
            f"/projects/{project_id}/timeline/narration/{event_id}",
            json={"text": "updated narration line", "end_ms": 1400},
        )
        self.assertEqual(200, patch_resp.status_code)
        self.assertEqual("updated narration line", patch_resp.json()["event"]["text"])

        proj = load_project(self.data_dir, project_id)
        self.assertEqual("tts_only", proj["settings"]["narration_mode"])

    def test_timeline_import_invalid_line_returns_line_aware_error(self) -> None:
        project_id = self._init_project("proj_timeline_err")
        resp = self.client.post(
            f"/projects/{project_id}/timeline/import",
            json={"content": "[00:00] valid\nbad line", "import_format": "timestamped_txt"},
        )
        self.assertEqual(400, resp.status_code)
        detail = resp.json()["detail"]
        self.assertEqual("invalid_timestamped_line", detail["code"])
        self.assertEqual(2, detail["line_number"])

    def test_tts_profile_save_get_and_preview_cache_reuse(self) -> None:
        project_id = self._init_project("proj_tts_profile")
        upsert_resp = self.client.post(
            f"/projects/{project_id}/tts/profile",
            json={
                "profile_id": "narrator_a",
                "display_name": "Narrator A",
                "voice_mode": "predefined_voice",
                "predefined_voice_id": "alloy",
                "params": {"speed_factor": 1.1, "temperature": 0.6},
            },
        )
        self.assertEqual(200, upsert_resp.status_code)
        self.assertEqual("narrator_a", upsert_resp.json()["profile"]["profile_id"])

        get_resp = self.client.get(f"/projects/{project_id}/tts/profile", params={"profile_id": "narrator_a"})
        self.assertEqual(200, get_resp.status_code)
        self.assertEqual("Narrator A", get_resp.json()["profile"]["display_name"])

        def fake_tts_or_silence(*, out_path: Path, duration_ms: int, **_: object) -> tuple[str, int]:
            _write_silent_wav(out_path, duration_ms=duration_ms)
            return "generated-sha", duration_ms

        preview_body = {
            "text": "Preview narration line",
            "duration_ms": 1200,
            "profile_id": "narrator_a",
            "params_override": {"seed": 7},
        }
        with (
            patch("backend.app.main.tts_or_silence", side_effect=fake_tts_or_silence) as tts_mock,
            patch("backend.app.pipeline.tts.probe_audio_duration_ms", return_value=1200),
        ):
            first = self.client.post(f"/projects/{project_id}/tts/preview", json=preview_body)
            second = self.client.post(f"/projects/{project_id}/tts/preview", json=preview_body)

        self.assertEqual(200, first.status_code)
        self.assertFalse(first.json()["cache_hit"])
        self.assertTrue(Path(first.json()["audio_path"]).exists())

        self.assertEqual(200, second.status_code)
        self.assertTrue(second.json()["cache_hit"])
        self.assertEqual(1, tts_mock.call_count)

    def test_action_validate_demo_queue_and_demo_runs_flow(self) -> None:
        project_id = self._init_project("proj_demo_flow")
        proj = load_project(self.data_dir, project_id)
        proj["timeline"]["action_events"] = [
            {"id": "a1", "at_ms": 0, "action": "goto", "target": "https://example.com"},
            {"id": "a2", "at_ms": 100, "action": "wait", "args": {"ms": 0}},
        ]
        save_project(self.data_dir, project_id, proj)

        validate_resp = self.client.post(f"/projects/{project_id}/timeline/actions/validate")
        self.assertEqual(200, validate_resp.status_code)
        self.assertEqual(2, validate_resp.json()["action_count"])

        fake_queue = _FakeQueue()
        with patch("backend.app.main.get_queue", return_value=fake_queue):
            run_resp = self.client.post(f"/projects/{project_id}/demo/run")
        self.assertEqual(200, run_resp.status_code)
        run_payload = run_resp.json()
        self.assertEqual("job_1", run_payload["job_id"])
        self.assertEqual("playwright_optional", run_payload["execution_mode"])
        self.assertEqual("demo_capture", run_payload["run_type"])
        self.assertEqual("/jobs/job_1", run_payload["status_url"])
        self.assertEqual("default", run_payload["queue_name"])
        self.assertTrue(run_payload["queued_at"])
        self.assertEqual(main.run_demo_capture_for_project, fake_queue.calls[0]["fn"])
        self.assertEqual((self.data_dir, project_id, "playwright_optional"), fake_queue.calls[0]["args"])
        self.assertEqual("demo_capture", fake_queue.calls[0]["kwargs"]["meta"]["run_type"])
        self.assertEqual(project_id, fake_queue.calls[0]["kwargs"]["meta"]["project_id"])

        proj = load_project(self.data_dir, project_id)
        proj["demo"]["runs"] = [
            {
                "run_id": "demo_1",
                "ok": False,
                "mode": "demo_capture_failed",
                "actions_total": 1,
                "actions_executed": 1,
                "drift_stats": {"count": 1},
                "stage_timings_ms": {"capture_ms": 1200, "total_ms": 1500},
                "error_summary": {"has_error": True, "message": "capture failed"},
            }
        ]
        proj["demo"]["last_run_id"] = "demo_1"
        save_project(self.data_dir, project_id, proj)
        runs_resp = self.client.get(f"/projects/{project_id}/demo/runs")
        self.assertEqual(200, runs_resp.status_code)
        runs_payload = runs_resp.json()
        self.assertEqual(1, len(runs_payload["runs"]))
        self.assertEqual(1, runs_payload["run_count"])
        self.assertEqual("demo_1", runs_payload["last_run_id"])
        self.assertGreater(runs_payload["history_limit"], 0)
        self.assertIn("stage_timings_ms", runs_payload["runs"][0])
        self.assertIn("drift_stats", runs_payload["runs"][0])
        self.assertIn("error_summary", runs_payload["runs"][0])

        proj = load_project(self.data_dir, project_id)
        proj["timeline"]["action_events"] = [{"id": "a3", "at_ms": 0, "action": "drag", "target": "#x"}]
        save_project(self.data_dir, project_id, proj)
        invalid_resp = self.client.post(f"/projects/{project_id}/timeline/actions/validate")
        self.assertEqual(400, invalid_resp.status_code)
        detail = invalid_resp.json()["detail"]
        self.assertIn("unsupported action", detail)
        self.assertIn("action_index=0", detail)
        self.assertIn("action_id=a3", detail)

    def test_render_and_run_alias_both_enqueue_pipeline(self) -> None:
        project_id = self._init_project("proj_render")
        fake_queue = _FakeQueue()
        with patch("backend.app.main.get_queue", return_value=fake_queue):
            render_resp = self.client.post(f"/projects/{project_id}/render")
            run_resp = self.client.post(f"/projects/{project_id}/run")

        self.assertEqual(200, render_resp.status_code)
        self.assertEqual(200, run_resp.status_code)
        self.assertEqual("render", render_resp.json()["run_type"])
        self.assertEqual("render", run_resp.json()["run_type"])
        self.assertEqual(project_id, render_resp.json()["project_id"])
        self.assertEqual(project_id, run_resp.json()["project_id"])
        self.assertEqual("/jobs/job_1", render_resp.json()["status_url"])
        self.assertEqual("/jobs/job_2", run_resp.json()["status_url"])
        self.assertEqual(2, len(fake_queue.calls))
        self.assertEqual(main.run_pipeline, fake_queue.calls[0]["fn"])
        self.assertEqual(main.run_pipeline, fake_queue.calls[1]["fn"])
        self.assertEqual((project_id,), fake_queue.calls[0]["args"])
        self.assertEqual((project_id,), fake_queue.calls[1]["args"])
        self.assertEqual("render", fake_queue.calls[0]["kwargs"]["meta"]["run_type"])
        self.assertEqual(project_id, fake_queue.calls[0]["kwargs"]["meta"]["project_id"])

    def test_job_status_maps_rq_states_and_handles_missing(self) -> None:
        redis_obj = object()
        with patch("backend.app.main.get_redis", return_value=redis_obj):
            with self.subTest("queued"):
                job = SimpleNamespace(
                    id="job-q",
                    is_started=False,
                    is_finished=False,
                    is_failed=False,
                    result=None,
                    exc_info=None,
                    origin="default",
                    func_name="backend.app.pipeline.pipeline_main.run_pipeline",
                    meta={"run_type": "render", "project_id": "proj_render", "queued_at": "2026-02-19T00:00:00+00:00"},
                    enqueued_at=datetime(2026, 2, 19, 0, 0, tzinfo=timezone.utc),
                    started_at=None,
                    ended_at=None,
                )
                with patch("backend.app.main.Job.fetch", return_value=job):
                    resp = self.client.get("/jobs/job-q")
                self.assertEqual(200, resp.status_code)
                self.assertEqual("queued", resp.json()["status"])
                self.assertEqual("render", resp.json()["run_type"])
                self.assertEqual("proj_render", resp.json()["project_id"])
                self.assertEqual("default", resp.json()["queue_name"])
                self.assertIn("T", resp.json()["enqueued_at"])

            with self.subTest("started"):
                job = SimpleNamespace(
                    id="job-s",
                    is_started=True,
                    is_finished=False,
                    is_failed=False,
                    result=None,
                    exc_info=None,
                    origin="default",
                    func_name="backend.app.demo_runner.jobs.run_demo_capture_for_project",
                    meta={"run_type": "demo_capture", "project_id": "proj_demo", "execution_mode": "playwright_optional"},
                    enqueued_at=datetime(2026, 2, 19, 0, 0, tzinfo=timezone.utc),
                    started_at=datetime(2026, 2, 19, 0, 1, tzinfo=timezone.utc),
                    ended_at=None,
                )
                with patch("backend.app.main.Job.fetch", return_value=job):
                    resp = self.client.get("/jobs/job-s")
                self.assertEqual("started", resp.json()["status"])
                self.assertEqual("demo_capture", resp.json()["run_type"])
                self.assertEqual("playwright_optional", resp.json()["execution_mode"])
                self.assertIn("T", resp.json()["started_at"])

            with self.subTest("finished"):
                job = SimpleNamespace(
                    id="job-f",
                    is_started=True,
                    is_finished=True,
                    is_failed=False,
                    result={"ok": True},
                    exc_info=None,
                    origin="default",
                    func_name="backend.app.pipeline.pipeline_main.run_pipeline",
                    meta={"run_type": "render", "project_id": "proj_done", "narration_mode": "unified"},
                    enqueued_at=datetime(2026, 2, 19, 0, 0, tzinfo=timezone.utc),
                    started_at=datetime(2026, 2, 19, 0, 1, tzinfo=timezone.utc),
                    ended_at=datetime(2026, 2, 19, 0, 2, tzinfo=timezone.utc),
                )
                with patch("backend.app.main.Job.fetch", return_value=job):
                    resp = self.client.get("/jobs/job-f")
                self.assertEqual("finished", resp.json()["status"])
                self.assertEqual({"ok": True}, resp.json()["result"])
                self.assertEqual("unified", resp.json()["narration_mode"])
                self.assertIn("T", resp.json()["ended_at"])

            with self.subTest("failed"):
                job = SimpleNamespace(
                    id="job-e",
                    is_started=True,
                    is_finished=False,
                    is_failed=True,
                    result=None,
                    exc_info="traceback",
                    origin="default",
                    func_name="backend.app.demo_runner.jobs.run_demo_capture_for_project",
                    meta={"run_type": "demo_capture", "project_id": "proj_fail"},
                    enqueued_at=datetime(2026, 2, 19, 0, 0, tzinfo=timezone.utc),
                    started_at=datetime(2026, 2, 19, 0, 1, tzinfo=timezone.utc),
                    ended_at=datetime(2026, 2, 19, 0, 2, tzinfo=timezone.utc),
                )
                with patch("backend.app.main.Job.fetch", return_value=job):
                    resp = self.client.get("/jobs/job-e")
                self.assertEqual("failed", resp.json()["status"])
                self.assertIn("traceback", resp.json()["error"])

            with self.subTest("missing"):
                with patch("backend.app.main.Job.fetch", side_effect=RuntimeError("missing")):
                    resp = self.client.get("/jobs/job-missing")
                self.assertEqual(404, resp.status_code)

    def test_health_deps_reports_redis_and_tts_states(self) -> None:
        redis_ok = MagicMock()
        redis_ok.ping.return_value = True

        self.test_settings.tts_endpoint = ""
        with (
            patch("backend.app.main.get_redis", return_value=redis_ok),
            patch(
                "backend.app.main.probe_playwright_dependencies",
                return_value={
                    "ok": True,
                    "python_package_ok": True,
                    "browser_ok": True,
                    "error": "",
                },
            ),
        ):
            ok_resp = self.client.get("/health/deps")
        self.assertEqual(200, ok_resp.status_code)
        ok_payload = ok_resp.json()
        self.assertTrue(ok_payload["ok"])
        self.assertTrue(ok_payload["redis"]["ok"])
        self.assertTrue(ok_payload["tts"]["ok"])
        self.assertTrue(ok_payload["playwright"]["ok"])
        self.assertEqual("playwright_optional", ok_payload["playwright"]["execution_mode"])
        self.assertFalse(ok_payload["playwright"]["required"])

        redis_ok = MagicMock()
        redis_ok.ping.return_value = True
        self.test_settings.tts_endpoint = "http://tts.example/tts"
        with (
            patch("backend.app.main.get_redis", return_value=redis_ok),
            patch("backend.app.main.httpx.Client") as client_cls,
            patch(
                "backend.app.main.probe_playwright_dependencies",
                return_value={
                    "ok": True,
                    "python_package_ok": True,
                    "browser_ok": True,
                    "error": "",
                },
            ),
        ):
            client = client_cls.return_value.__enter__.return_value
            client.get.side_effect = RuntimeError("tts unavailable")
            err_resp = self.client.get("/health/deps")
        self.assertEqual(200, err_resp.status_code)
        err_payload = err_resp.json()
        self.assertFalse(err_payload["ok"])
        self.assertTrue(err_payload["redis"]["ok"])
        self.assertFalse(err_payload["tts"]["ok"])
        self.assertIn("tts unavailable", err_payload["tts"]["error"])

        redis_ok = MagicMock()
        redis_ok.ping.return_value = True
        self.test_settings.tts_endpoint = ""
        self.test_settings.demo_capture_execution_mode = "playwright_required"
        with (
            patch("backend.app.main.get_redis", return_value=redis_ok),
            patch(
                "backend.app.main.probe_playwright_dependencies",
                return_value={
                    "ok": False,
                    "python_package_ok": False,
                    "browser_ok": False,
                    "error": "Playwright missing",
                },
            ),
        ):
            pw_resp = self.client.get("/health/deps")
        self.assertEqual(200, pw_resp.status_code)
        pw_payload = pw_resp.json()
        self.assertFalse(pw_payload["ok"])
        self.assertFalse(pw_payload["playwright"]["ok"])
        self.assertTrue(pw_payload["playwright"]["required"])
        self.assertEqual("playwright_required", pw_payload["playwright"]["execution_mode"])


if __name__ == "__main__":
    unittest.main()
