from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.app.config import settings
from backend.app.storage import load_project, save_project, append_log, project_dir, write_demo_context_md
from backend.app.pipeline.utils import ffprobe_json, utc_now_iso
from backend.app.pipeline.tts import tts_or_silence
from backend.app.pipeline.srt import write_srt
from backend.app.pipeline.mux import write_filter_script, mix_narration_wav, mux_final_mp4, attach_srt_mp4

# Rate limits: GLM-4.6V = 10 concurrent, GLM-5 = 3 concurrent
VISION_BATCH_SIZE = 10
REWRITE_BATCH_SIZE = 3
TTS_BATCH_SIZE = 3


def _video_duration_s(probe: dict[str, Any]) -> float:
    fmt = probe.get("format", {})
    dur = fmt.get("duration")
    if dur is None:
        return 0.0
    return float(dur)


def _video_has_audio(probe: dict[str, Any]) -> bool:
    for st in probe.get("streams", []):
        if st.get("codec_type") == "audio":
            return True
    return False


def _video_dims_fps(probe: dict[str, Any]) -> tuple[int | None, int | None, float | None]:
    for st in probe.get("streams", []):
        if st.get("codec_type") == "video":
            w = st.get("width")
            h = st.get("height")
            afr = st.get("avg_frame_rate")
            fps = None
            if isinstance(afr, str) and "/" in afr:
                num, den = afr.split("/", 1)
                try:
                    fps = float(num) / float(den)
                except Exception:
                    fps = None
            return w, h, fps
    return None, None, None


def _find_global_guidance(plan: dict[str, Any], segment_id: int) -> dict[str, Any] | None:
    for entry in plan.get("segments", []) or []:
        try:
            if int(entry.get("segment_id")) == segment_id:
                return entry
        except Exception:
            continue
    return None


def _pick_candidate(candidates: list[str], guidance: dict[str, Any] | None) -> tuple[int, str]:
    if not candidates:
        return 0, "Continue the demo and show the next step."
    idx = 0
    if guidance:
        raw = guidance.get("preferred_candidate_index")
        try:
            idx = int(raw)
        except Exception:
            idx = 0
    if idx < 0 or idx >= len(candidates):
        idx = 0
    return idx, candidates[idx]


def run_segment_pipeline(project_id: str) -> dict[str, Any]:
    """
    Run the segment-based narration pipeline.

    This is the original pipeline that segments the video, analyzes each segment
    with vision, and generates per-segment narration.
    """
    # Legacy pipeline imports are deferred so default runtime can avoid loading
    # segmentation/vision/rewrite modules unless legacy mode is selected.
    from backend.app.pipeline.segmenter import build_segments
    from backend.app.pipeline.keyframes import keyframes_for_segment
    from backend.app.pipeline.vision import analyze_segment
    from backend.app.pipeline.rewrite import rewrite_to_fit
    from backend.app.pipeline.global_planning import plan_global_narration

    data_dir = settings.data_dir
    pdir = project_dir(data_dir, project_id)
    input_mp4 = pdir / "input.mp4"
    work_dir = pdir / "work"
    exports_dir = pdir / "exports"

    append_log(data_dir, project_id, f"[{utc_now_iso()}] pipeline start")

    proj = load_project(data_dir, project_id)
    append_log(data_dir, project_id, f"[{utc_now_iso()}] project loaded from disk")

    # Probe source metadata and sync derived values.
    probe = ffprobe_json(input_mp4)
    duration_s = _video_duration_s(probe)
    duration_ms = int(round(duration_s * 1000))
    w, h, fps = _video_dims_fps(probe)
    has_audio = _video_has_audio(probe)
    proj["source"]["video"]["duration_ms"] = duration_ms
    proj["source"]["video"]["width"] = w
    proj["source"]["video"]["height"] = h
    proj["source"]["video"]["fps"] = fps
    proj["source"]["video"]["has_audio"] = has_audio

    project_context = str((proj.get("settings") or {}).get("demo_context") or "")
    write_demo_context_md(data_dir, project_id, project_context)

    planning = proj.get("planning")
    if not isinstance(planning, dict):
        planning = {}
        proj["planning"] = planning
    proj["planning"]["narration_global"] = {"status": "running"}
    save_project(data_dir, project_id, proj)

    seg_cfg = proj["settings"]["segmentation"]
    analysis_fps = int(seg_cfg.get("analysis_fps", 10))
    min_seg_ms = int(seg_cfg.get("min_seg_ms", 2000))
    max_seg_ms = int(seg_cfg.get("max_seg_ms", 8000))

    # segmentation + proxy + keyframes
    proxy_mp4, proxy_sha, segments = build_segments(
        input_mp4=input_mp4,
        work_dir=work_dir,
        duration_s=duration_s,
        analysis_fps=analysis_fps,
        min_seg_ms=min_seg_ms,
        max_seg_ms=max_seg_ms
    )
    proj["source"]["proxy_video"] = {
        "path": str(proxy_mp4),
        "sha256": proxy_sha,
        "analysis_fps": analysis_fps
    }

    # Build segment objects
    proj_segments = []
    for seg in segments:
        kfs = keyframes_for_segment(input_mp4, work_dir, seg.id, seg.start_ms, seg.end_ms)
        proj_segments.append({
            "id": seg.id,
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "keyframes": [kf.__dict__ for kf in kfs],
            "vision": {"status": "not_started"},
            "narration": {"target_words": 0, "selected_text": "", "pause_hint_ms": 0, "history": []},
            "tts": {"status": "not_started", "audio_path": "", "attempts": []},
            "mixing": {"timeline_start_ms": seg.start_ms, "gain_db": 0, "fade_in_ms": 10, "fade_out_ms": 30}
        })
    proj["segments"] = proj_segments
    save_project(data_dir, project_id, proj)
    append_log(data_dir, project_id, f"[{utc_now_iso()}] segmented into {len(proj_segments)} segments")

    # For local MVP we use local file paths as image URLs by serving them is not implemented.
    # If you want GLM-4.6V, host keyframes somewhere accessible and swap to URLs.
    # We still persist payloads for reproducibility.

    # Narration settings
    nar_cfg = proj["settings"]["narration"]
    wps = float(nar_cfg.get("wps", 2.25))
    min_words = int(nar_cfg.get("min_words", 4))
    max_words = int(nar_cfg.get("max_words", 28))

    # TTS settings
    tts_cfg = proj["settings"]["tts"]
    tts_params = dict(tts_cfg.get("default_params") or {})
    tts_endpoint = settings.tts_endpoint or tts_cfg.get("endpoint") or ""
    if tts_endpoint:
        proj["settings"]["tts"]["endpoint"] = tts_endpoint
    ref_audio = tts_cfg.get("reference_audio_path")
    if ref_audio:
        tts_params["audio_prompt_path"] = ref_audio

    vision_digest: list[dict[str, Any]] = []

    # Helper function to process a single segment's vision
    def process_vision(seg: dict) -> tuple[int, dict, dict]:
        sid = int(seg["id"])
        s_ms = int(seg["start_ms"])
        e_ms = int(seg["end_ms"])
        seg_dur_ms = e_ms - s_ms

        payload_path = work_dir / f"seg{sid}_vision_payload.json"
        raw_path = work_dir / f"seg{sid}_vision_raw.txt"

        image_urls = []
        try:
            for kf in seg.get("keyframes", []):
                p = Path(kf["path"])
                if p.exists():
                    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                    image_urls.append(f"data:image/png;base64,{b64}")
        except Exception:
            image_urls = []

        vision_result = {}
        try:
            event = analyze_segment(
                sid,
                s_ms,
                e_ms,
                image_urls,
                persist_payload_path=payload_path,
                persist_raw_path=raw_path,
                project_context=project_context
            )
            vision_result = {
                "status": "ok",
                "model": settings.zai_vision_model,
                "request_payload_path": str(payload_path),
                "raw_response_path": str(raw_path),
                "event_json": event
            }
        except Exception as ex:
            vision_result = {"status": "error", "error": str(ex)}

        event_payload = vision_result.get("event_json") or {}
        digest_entry = {
            "segment_id": sid,
            "duration_ms": seg_dur_ms,
            "result": event_payload.get("result") or "",
            "narration_candidates": event_payload.get("narration_candidates") or [],
            "on_screen_text": event_payload.get("on_screen_text") or []
        }
        return sid, vision_result, digest_entry

    # Vision pass - PARALLEL processing
    print(f"[Pipeline] Starting vision analysis with batch size {VISION_BATCH_SIZE}")
    with ThreadPoolExecutor(max_workers=VISION_BATCH_SIZE) as executor:
        futures = {executor.submit(process_vision, seg): seg for seg in proj["segments"]}
        for future in as_completed(futures):
            sid, vision_result, digest_entry = future.result()
            proj["segments"][sid]["vision"] = vision_result
            vision_digest.append(digest_entry)
            save_project(data_dir, project_id, proj)
            print(f"[Pipeline] Vision complete for segment {sid}")

    # Global narration planning pass.
    global_plan_payload = work_dir / "global_narration_plan_payload.json"
    global_plan_raw = work_dir / "global_narration_plan_raw.txt"
    global_plan = plan_global_narration(
        project_context=project_context,
        segments_digest=vision_digest,
        persist_payload_path=global_plan_payload,
        persist_raw_path=global_plan_raw
    )
    proj["planning"]["narration_global"] = {
        "status": global_plan.get("status", "ok"),
        "summary": global_plan.get("summary", ""),
        "segments": global_plan.get("segments", []),
        "artifact_payload_path": str(global_plan_payload),
        "artifact_raw_path": str(global_plan_raw)
    }
    save_project(data_dir, project_id, proj)

    # Rewrite + TTS pass, guided by global planning output.
    # Helper function for rewrite
    def process_rewrite(seg: dict) -> tuple[int, dict]:
        sid = int(seg["id"])
        s_ms = int(seg["start_ms"])
        e_ms = int(seg["end_ms"])
        seg_dur_ms = e_ms - s_ms
        candidates = (seg.get("vision", {}).get("event_json") or {}).get("narration_candidates") or []
        guidance = _find_global_guidance(proj["planning"]["narration_global"], sid)
        _, candidate = _pick_candidate(candidates, guidance)
        on_screen_text = (seg.get("vision", {}).get("event_json") or {}).get("on_screen_text") or []
        action_summary = (seg.get("vision", {}).get("event_json") or {}).get("result") or ""

        target = int(round((seg_dur_ms / 1000.0) * wps))
        target = max(min_words, min(max_words, target))

        rewrite_payload_path = work_dir / f"seg{sid}_rewrite_payload.json"
        rewrite_raw_path = work_dir / f"seg{sid}_rewrite_raw.txt"
        rewrite = rewrite_to_fit(
            segment_id=sid,
            duration_ms=seg_dur_ms,
            target_words=target,
            candidate=candidate,
            on_screen_text=on_screen_text,
            action_summary=action_summary,
            project_context=project_context,
            global_summary=proj["planning"]["narration_global"].get("summary", ""),
            segment_guidance=guidance or {},
            persist_payload_path=str(rewrite_payload_path),
            persist_raw_path=str(rewrite_raw_path)
        )
        narration_result = {
            "target_words": target,
            "selected_text": rewrite["narration"],
            "pause_hint_ms": int(rewrite.get("pause_hint_ms") or 0),
            "history": [{
                "source": "glm_5_rewrite",
                "text": rewrite["narration"],
                "word_count": int(rewrite.get("word_count") or 0),
                "created_at": utc_now_iso(),
                "request_payload_path": str(rewrite_payload_path),
                "raw_response_path": str(rewrite_raw_path)
            }]
        }
        return sid, narration_result

    # Helper function for TTS
    def process_tts(seg: dict) -> tuple[int, dict]:
        sid = int(seg["id"])
        seg_dur_ms = int(seg["end_ms"]) - int(seg["start_ms"])
        wav_path = work_dir / f"seg{sid}.wav"
        text = seg["narration"]["selected_text"]

        tts_result = {}
        try:
            audio_sha, audio_dur = tts_or_silence(text=text, out_path=wav_path, duration_ms=seg_dur_ms, params=tts_params)
            tts_result = {
                "status": "ok",
                "audio_path": str(wav_path),
                "audio_sha256": audio_sha,
                "audio_duration_ms": audio_dur,
                "attempts": [{
                    "created_at": utc_now_iso(),
                    "text": text,
                    "params": tts_params,
                    "result": {"status": "ok", "audio_path": str(wav_path), "audio_duration_ms": audio_dur}
                }]
            }
        except Exception as ex:
            tts_result = {
                "status": "error",
                "audio_path": str(wav_path),
                "attempts": [{
                    "created_at": utc_now_iso(),
                    "text": text,
                    "params": tts_params,
                    "result": {"status": "error", "error": str(ex)}
                }]
            }
        return sid, tts_result

    # Rewrite pass - SEQUENTIAL (to track previous narrations and avoid repetition)
    print("[Pipeline] Starting rewrite (sequential for narrative coherence)")
    previous_narrations: list[str] = []
    for seg in proj["segments"]:
        sid = int(seg["id"])
        s_ms = int(seg["start_ms"])
        e_ms = int(seg["end_ms"])
        seg_dur_ms = e_ms - s_ms
        candidates = (seg.get("vision", {}).get("event_json") or {}).get("narration_candidates") or []
        guidance = _find_global_guidance(proj["planning"]["narration_global"], sid)
        _, candidate = _pick_candidate(candidates, guidance)
        on_screen_text = (seg.get("vision", {}).get("event_json") or {}).get("on_screen_text") or []
        action_summary = (seg.get("vision", {}).get("event_json") or {}).get("result") or ""

        target = int(round((seg_dur_ms / 1000.0) * wps))
        target = max(min_words, min(max_words, target))

        rewrite_payload_path = work_dir / f"seg{sid}_rewrite_payload.json"
        rewrite_raw_path = work_dir / f"seg{sid}_rewrite_raw.txt"
        rewrite = rewrite_to_fit(
            segment_id=sid,
            duration_ms=seg_dur_ms,
            target_words=target,
            candidate=candidate,
            on_screen_text=on_screen_text,
            action_summary=action_summary,
            project_context=project_context,
            global_summary=proj["planning"]["narration_global"].get("summary", ""),
            segment_guidance=guidance or {},
            previous_narrations=previous_narrations,
            persist_payload_path=str(rewrite_payload_path),
            persist_raw_path=str(rewrite_raw_path)
        )
        narration_result = {
            "target_words": target,
            "selected_text": rewrite["narration"],
            "pause_hint_ms": int(rewrite.get("pause_hint_ms") or 0),
            "history": [{
                "source": "glm_5_rewrite",
                "text": rewrite["narration"],
                "word_count": int(rewrite.get("word_count") or 0),
                "created_at": utc_now_iso(),
                "request_payload_path": str(rewrite_payload_path),
                "raw_response_path": str(rewrite_raw_path)
            }]
        }
        proj["segments"][sid]["narration"] = narration_result
        previous_narrations.append(rewrite["narration"])
        save_project(data_dir, project_id, proj)
        print(f"[Pipeline] Rewrite complete for segment {sid}")

    # TTS pass - PARALLEL
    print(f"[Pipeline] Starting TTS with batch size {TTS_BATCH_SIZE}")
    with ThreadPoolExecutor(max_workers=TTS_BATCH_SIZE) as executor:
        futures = {executor.submit(process_tts, seg): seg for seg in proj["segments"]}
        for future in as_completed(futures):
            sid, tts_result = future.result()
            proj["segments"][sid]["tts"] = tts_result
            save_project(data_dir, project_id, proj)
            print(f"[Pipeline] TTS complete for segment {sid}")

    append_log(data_dir, project_id, f"[{utc_now_iso()}] per-segment narration+tts complete")

    srt_path = exports_dir / "script.srt"
    write_srt(proj["segments"], srt_path)

    wavs = [Path(seg["tts"]["audio_path"]) for seg in proj["segments"]]
    filter_script = work_dir / "mix_audio.ffscript"
    write_filter_script(proj["segments"], filter_script, total_duration_ms=duration_ms)
    narration_wav = exports_dir / "narration_mix.wav"
    mix_narration_wav(wavs, filter_script, narration_wav)

    final_mp4 = exports_dir / "final.mp4"
    mux_final_mp4(input_mp4, narration_wav, final_mp4)

    final_with_caps = exports_dir / "final_with_captions.mp4"
    attach_srt_mp4(final_mp4, srt_path, final_with_caps)

    proj["exports"]["artifacts"] = {
        "script_srt_path": str(srt_path),
        "narration_mix_wav_path": str(narration_wav),
        "final_mp4_path": str(final_mp4),
        "final_mp4_with_captions_path": str(final_with_caps)
    }
    proj["exports"]["ffmpeg"] = {
        "commands": [
            "proxy: ffmpeg -vf scale=-2:540,fps=analysis_fps -an ...",
            "mix: ffmpeg -filter_complex_script mix_audio.ffscript ...",
            "mux: ffmpeg -i input.mp4 -i narration_mix.wav -c:v copy -c:a aac ..."
        ],
        "filter_complex_script_path": str(filter_script)
    }
    proj["exports"]["exported_at"] = utc_now_iso()
    save_project(data_dir, project_id, proj)
    append_log(data_dir, project_id, f"[{utc_now_iso()}] export complete: {final_mp4}")
    return {"ok": True, "project_id": project_id, "final_mp4": str(final_mp4), "mode": "segment"}


def run_pipeline(project_id: str) -> dict[str, Any]:
    """
    Main pipeline entry point with mode selection.

    Selects between tts-only, holistic, and segment-based narration pipelines
    based on configuration.

    Settings:
        narration_mode: "tts_only" (default), "segment", or "holistic"
        holistic_fallback_to_segment: If true, falls back to segment mode on holistic failure
    """
    # Get settings from project or global config
    proj = load_project(settings.data_dir, project_id)
    project_settings = proj.get("settings", {})

    # Check for narration mode in project settings first, then global config
    narration_mode = project_settings.get("narration_mode", getattr(settings, "narration_mode", "tts_only"))
    holistic_fallback = project_settings.get("holistic_fallback_to_segment", True)

    # Also check holistic-specific settings
    holistic_cfg = project_settings.get("holistic", {})
    if holistic_cfg.get("enabled"):
        narration_mode = "holistic"

    if narration_mode in {"tts_only", "timeline"}:
        print(f"[Pipeline] Running in tts_only mode for project {project_id}")
        from backend.app.pipeline.tts_only import run_tts_only_pipeline

        return run_tts_only_pipeline(project_id)
    elif narration_mode in {"unified", "timeline_unified"}:
        print(f"[Pipeline] Running in unified mode for project {project_id}")
        from backend.app.pipeline.unified import run_unified_pipeline

        return run_unified_pipeline(project_id, settings.data_dir)
    elif narration_mode in {"holistic", "legacy_holistic"}:
        try:
            print(f"[Pipeline] Running in holistic mode for project {project_id}")
            from backend.app.pipeline.holistic import run_holistic_pipeline
            return run_holistic_pipeline(project_id)
        except Exception as e:
            if holistic_fallback:
                print(f"[Pipeline] Holistic pipeline failed ({e}), falling back to segment mode")
                append_log(settings.data_dir, project_id, f"[{utc_now_iso()}] holistic failed, falling back: {e}")
                return run_segment_pipeline(project_id)
            else:
                raise
    elif narration_mode in {"segment", "legacy_segment"}:
        return run_segment_pipeline(project_id)
    else:
        # Unknown mode falls back to the default non-legacy path.
        from backend.app.pipeline.tts_only import run_tts_only_pipeline

        return run_tts_only_pipeline(project_id)
