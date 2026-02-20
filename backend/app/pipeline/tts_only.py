from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from backend.app.config import settings
from backend.app.pipeline.mux import attach_srt_mp4, mix_narration_wav, mux_final_mp4, write_filter_script
from backend.app.pipeline.srt import write_srt
from backend.app.pipeline.tts import probe_audio_duration_ms, tts_or_silence
from backend.app.pipeline.utils import ffprobe_json, utc_now_iso
from backend.app.storage import MAX_RENDER_HISTORY, append_log, append_render_history, load_project, project_dir, save_project
from backend.app.tts.cache import build_tts_cache_key, restore_tts_cache, store_tts_cache, tts_cache_path
from backend.app.tts.profiles import ensure_tts_profiles, resolve_tts_endpoint, resolve_tts_params, resolve_tts_profile


def _video_duration_ms(path: Path) -> int:
    probe = ffprobe_json(path)
    return int(round(float(probe.get("format", {}).get("duration") or 0.0) * 1000))


def _timeline_to_segments(timeline: dict[str, Any], video_duration_ms: int) -> list[dict[str, Any]]:
    events = timeline.get("narration_events")
    if not isinstance(events, list):
        return []

    normalized_events: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        text = str(event.get("text") or "").strip()
        if not text:
            continue
        start_ms = int(event.get("start_ms") or 0)
        end_ms = int(event.get("end_ms") or start_ms)
        normalized_events.append(
            {
                "id": str(event.get("id") or f"n{idx + 1}"),
                "start_ms": max(0, start_ms),
                "end_ms": max(0, end_ms),
                "text": text,
                "voice_profile_id": str(event.get("voice_profile_id") or "default"),
            }
        )

    normalized_events.sort(key=lambda e: (int(e["start_ms"]), str(e["id"])))

    segments: list[dict[str, Any]] = []
    for idx, event in enumerate(normalized_events):
        start_ms = int(event["start_ms"])
        if start_ms >= video_duration_ms:
            continue

        end_ms = int(event["end_ms"])
        if end_ms <= start_ms:
            if idx + 1 < len(normalized_events):
                end_ms = int(normalized_events[idx + 1]["start_ms"])
            else:
                end_ms = min(video_duration_ms, start_ms + 3000)
        end_ms = min(video_duration_ms, max(end_ms, start_ms + 500))

        segments.append(
            {
                "id": idx,
                "event_id": event["id"],
                "start_ms": start_ms,
                "end_ms": end_ms,
                "voice_profile_id": event["voice_profile_id"],
                "narration": {"selected_text": event["text"]},
                "tts": {"status": "not_started", "audio_path": "", "attempts": []},
                "mixing": {"timeline_start_ms": start_ms, "gain_db": 0, "fade_in_ms": 10, "fade_out_ms": 30},
            }
        )
    return segments


def run_tts_only_pipeline(
    project_id: str,
    source_video_path: str | None = None,
    render_mode: str = "tts_only",
    render_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data_dir = settings.data_dir
    pdir = project_dir(data_dir, project_id)
    input_mp4 = Path(source_video_path) if source_video_path else pdir / "input.mp4"
    work_dir = pdir / "work" / "tts_only"
    exports_dir = pdir / "exports"
    cache_dir = pdir / "cache" / "tts"
    work_dir.mkdir(parents=True, exist_ok=True)
    exports_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    append_log(data_dir, project_id, f"[{utc_now_iso()}] tts_only pipeline start")
    t0 = time.perf_counter()
    proj = load_project(data_dir, project_id)
    ensure_tts_profiles(proj)

    if not input_mp4.exists():
        fallback_input = pdir / "input.mp4"
        if fallback_input.exists():
            input_mp4 = fallback_input
        else:
            raise RuntimeError(f"Source video not found: {input_mp4}")

    video_duration_ms = _video_duration_ms(input_mp4)
    timeline = proj.get("timeline")
    if not isinstance(timeline, dict):
        raise RuntimeError("Timeline missing from project")

    segments = _timeline_to_segments(timeline, video_duration_ms)
    if not segments:
        raise RuntimeError("No narration events available in timeline")

    tts_mode = settings.tts_mode
    all_wavs: list[Path] = []
    cache_hits = 0
    generated = 0
    stage_timings: dict[str, int] = {}

    t_tts_start = time.perf_counter()

    for seg in segments:
        text = seg["narration"]["selected_text"]
        seg_duration = int(seg["end_ms"]) - int(seg["start_ms"])
        event_profile_id = str(seg.get("voice_profile_id") or "default")
        profile = resolve_tts_profile(proj, event_profile_id)
        endpoint = resolve_tts_endpoint(proj, profile, fallback_endpoint=settings.tts_endpoint)
        params = resolve_tts_params(proj, profile)

        cache_key = build_tts_cache_key(
            text=text,
            params=params,
            endpoint=endpoint,
            mode=tts_mode,
            audio_prompt_path=params.get("audio_prompt_path"),
            model_signature=f"{tts_mode}:{profile.get('provider', 'chatterbox')}",
        )
        cached_wav = tts_cache_path(cache_dir, cache_key)
        out_wav = work_dir / f"seg{seg['id']:03d}.wav"

        used_cache = restore_tts_cache(cached_wav, out_wav)
        if used_cache:
            cache_hits += 1
            audio_sha = cache_key
            audio_dur = probe_audio_duration_ms(out_wav)
        else:
            generated += 1
            audio_sha, audio_dur = tts_or_silence(
                text=text,
                out_path=out_wav,
                duration_ms=seg_duration,
                params=params,
                endpoint=endpoint,
                mode=tts_mode,
                postprocess=True,
            )
            store_tts_cache(out_wav, cached_wav)

        seg["tts"] = {
            "status": "ok",
            "audio_path": str(out_wav),
            "audio_sha256": audio_sha,
            "audio_duration_ms": int(audio_dur),
            "attempts": [
                {
                    "created_at": utc_now_iso(),
                    "text": text,
                    "params": params,
                    "result": {
                        "status": "ok",
                        "audio_path": str(out_wav),
                        "audio_duration_ms": int(audio_dur),
                        "cache_hit": used_cache,
                    },
                }
            ],
        }
        all_wavs.append(out_wav)
    stage_timings["tts_ms"] = int(round((time.perf_counter() - t_tts_start) * 1000))

    t_mix_start = time.perf_counter()
    srt_path = exports_dir / "script.srt"
    write_srt(segments, srt_path)

    filter_script = work_dir / "mix_audio.ffscript"
    write_filter_script(segments, filter_script, total_duration_ms=video_duration_ms)
    narration_wav = exports_dir / "narration_mix.wav"
    mix_narration_wav(all_wavs, filter_script, narration_wav)

    final_mp4 = exports_dir / "final.mp4"
    mux_final_mp4(input_mp4, narration_wav, final_mp4)
    final_with_caps = exports_dir / "final_with_captions.mp4"
    attach_srt_mp4(final_mp4, srt_path, final_with_caps)
    stage_timings["mix_mux_ms"] = int(round((time.perf_counter() - t_mix_start) * 1000))

    proj["exports"]["artifacts"] = {
        "script_srt_path": str(srt_path),
        "narration_mix_wav_path": str(narration_wav),
        "final_mp4_path": str(final_mp4),
        "final_mp4_with_captions_path": str(final_with_caps),
    }
    proj["exports"]["ffmpeg"] = {
        "commands": [
            "mix: ffmpeg -filter_complex_script mix_audio.ffscript ...",
            "mux: ffmpeg -i input.mp4 -i narration_mix.wav -c:v copy -c:a aac ...",
        ],
        "filter_complex_script_path": str(filter_script),
    }
    proj["exports"]["exported_at"] = utc_now_iso()

    stage_timings["total_ms"] = int(round((time.perf_counter() - t0) * 1000))

    render_id = f"render_{utc_now_iso().replace(':', '').replace('-', '')}"
    correlation = dict(render_context or {})
    if "demo_run_id" not in correlation:
        correlation["demo_run_id"] = None
    render_record = {
        "render_id": render_id,
        "created_at": utc_now_iso(),
        "status": "completed",
        "mode": render_mode,
        "segments": len(segments),
        "cache_hits": cache_hits,
        "generated_segments": generated,
        "final_mp4_path": str(final_mp4),
        "source_video_path": str(input_mp4),
        "stage_timings_ms": stage_timings,
        "error_summary": {
            "has_error": False,
            "message": "",
            "failed_actions": 0,
            "failed_action_ids": [],
            "error_types": {},
        },
        "correlation": correlation,
        "history_limit": MAX_RENDER_HISTORY,
    }
    render_record = append_render_history(proj, render_record, render_id=render_id, history_limit=MAX_RENDER_HISTORY)

    save_project(data_dir, project_id, proj)
    append_log(data_dir, project_id, f"[{utc_now_iso()}] tts_only export complete: {final_mp4}")
    return {
        "ok": True,
        "project_id": project_id,
        "final_mp4": str(final_mp4),
        "mode": render_mode,
        "segments": len(segments),
        "cache_hits": cache_hits,
        "generated_segments": generated,
        "source_video_path": str(input_mp4),
        "stage_timings_ms": stage_timings,
        "render_id": str(render_record.get("render_id") or render_id),
        "correlation": dict(render_record.get("correlation") or correlation),
    }
