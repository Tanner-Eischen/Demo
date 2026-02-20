"""
Holistic pipeline orchestration.

Coordinates the full flow: script generation -> keyframe extraction ->
vision matching -> script splitting -> TTS -> mixing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.app.config import settings
from backend.app.storage import load_project, save_project, append_log, project_dir
from backend.app.pipeline.holistic.models import VideoMetadata
from backend.app.pipeline.holistic.script_generator import generate_holistic_script
from backend.app.pipeline.holistic.timing_matcher import (
    extract_strategic_keyframes,
    match_narration_to_visuals,
)
from backend.app.pipeline.holistic.script_splitter import (
    split_script_by_timing,
    convert_split_script_to_segments,
)
from backend.app.pipeline.utils import ffprobe_json, utc_now_iso
from backend.app.pipeline.tts import tts_or_silence
from backend.app.pipeline.srt import write_srt
from backend.app.pipeline.mux import (
    write_filter_script,
    mix_narration_wav,
    mux_final_mp4,
    attach_srt_mp4,
)


def _video_duration_s(probe: dict[str, Any]) -> float:
    fmt = probe.get("format", {})
    dur = fmt.get("duration")
    if dur is None:
        return 0.0
    return float(dur)


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


def run_holistic_pipeline(project_id: str) -> dict[str, Any]:
    """
    Run the holistic narration pipeline for a project.

    This pipeline:
    1. Generates a cohesive narration script from project context
    2. Extracts strategic keyframes uniformly across the video
    3. Uses vision matching to connect narration sections to keyframes
    4. Splits the script into timed sections
    5. Generates TTS audio for each section
    6. Mixes and muxes the final video

    Args:
        project_id: The project ID to process

    Returns:
        Dictionary with ok status and final output path
    """
    data_dir = settings.data_dir
    pdir = project_dir(data_dir, project_id)
    input_mp4 = pdir / "input.mp4"
    work_dir = pdir / "work" / "holistic"
    exports_dir = pdir / "exports"

    # Ensure work directory exists
    from backend.app.pipeline.utils import ensure_dir
    ensure_dir(work_dir)
    ensure_dir(exports_dir)

    append_log(data_dir, project_id, f"[{utc_now_iso()}] holistic pipeline start")

    # Load project
    proj = load_project(data_dir, project_id)
    append_log(data_dir, project_id, f"[{utc_now_iso()}] project loaded")

    # Get project context
    project_context = str((proj.get("settings") or {}).get("demo_context") or "")

    # Get narration settings
    nar_cfg = proj.get("settings", {}).get("narration", {})
    wps = float(nar_cfg.get("wps", 2.25))
    min_words = int(nar_cfg.get("min_words", 4))
    max_words = int(nar_cfg.get("max_words", 28))

    # Get holistic settings
    holistic_cfg = proj.get("settings", {}).get("holistic", {})
    keyframe_density = float(holistic_cfg.get("keyframe_density", 1.0))
    confidence_threshold = float(holistic_cfg.get("match_confidence_threshold", 0.5))

    # Probe source video
    probe = ffprobe_json(input_mp4)
    duration_s = _video_duration_s(probe)
    duration_ms = int(round(duration_s * 1000))
    w, h, fps = _video_dims_fps(probe)

    video_metadata = VideoMetadata(
        duration_ms=duration_ms,
        estimated_scene_count=max(3, int(duration_s / 3)),  # Estimate ~3s per scene
        width=w,
        height=h,
        fps=fps,
    )

    # Update project state
    holistic_state = proj.setdefault("holistic", {})
    holistic_state["status"] = "running"
    holistic_state["started_at"] = utc_now_iso()
    save_project(data_dir, project_id, proj)

    # TTS settings
    tts_cfg = proj.get("settings", {}).get("tts", {})
    tts_params = dict(tts_cfg.get("default_params") or {})
    tts_endpoint = settings.tts_endpoint or tts_cfg.get("endpoint") or ""
    if tts_endpoint:
        proj["settings"]["tts"]["endpoint"] = tts_endpoint
    ref_audio = tts_cfg.get("reference_audio_path")
    if ref_audio:
        tts_params["audio_prompt_path"] = ref_audio

    try:
        # Step 1: Generate holistic script
        print("[Holistic Pipeline] Step 1: Generating holistic script...")
        append_log(data_dir, project_id, f"[{utc_now_iso()}] generating holistic script")

        script_payload_path = work_dir / "holistic_script_payload.json"
        script_raw_path = work_dir / "holistic_script_raw.txt"

        holistic_script = generate_holistic_script(
            project_context=project_context,
            video_metadata=video_metadata,
            persist_payload_path=script_payload_path,
            persist_raw_path=script_raw_path,
        )

        holistic_state["script"] = holistic_script.to_dict()
        holistic_state["script"]["artifact_payload_path"] = str(script_payload_path)
        holistic_state["script"]["artifact_raw_path"] = str(script_raw_path)
        save_project(data_dir, project_id, proj)

        print(f"[Holistic Pipeline] Generated script with {len(holistic_script.sections)} sections")

        # Step 2: Extract strategic keyframes
        print("[Holistic Pipeline] Step 2: Extracting strategic keyframes...")
        append_log(data_dir, project_id, f"[{utc_now_iso()}] extracting keyframes")

        keyframes = extract_strategic_keyframes(
            video_path=input_mp4,
            work_dir=work_dir / "keyframes",
            video_metadata=video_metadata,
            density_factor=keyframe_density,
        )

        holistic_state["keyframes"] = [kf.to_dict() for kf in keyframes]
        save_project(data_dir, project_id, proj)

        print(f"[Holistic Pipeline] Extracted {len(keyframes)} keyframes")

        # Step 3: Match narration to visuals
        print("[Holistic Pipeline] Step 3: Matching narration to visuals...")
        append_log(data_dir, project_id, f"[{utc_now_iso()}] matching narration to visuals")

        timing_plan_path = work_dir / "timing_plan.json"

        timing_plan = match_narration_to_visuals(
            script=holistic_script,
            keyframes=keyframes,
            project_context=project_context,
            confidence_threshold=confidence_threshold,
            persist_path=timing_plan_path,
        )

        holistic_state["timing_plan"] = timing_plan.to_dict()
        holistic_state["timing_plan"]["artifact_path"] = str(timing_plan_path)
        save_project(data_dir, project_id, proj)

        print(f"[Holistic Pipeline] Created timing plan with {len(timing_plan.matches)} matches")

        # Step 4: Split script by timing
        print("[Holistic Pipeline] Step 4: Splitting script by timing...")
        append_log(data_dir, project_id, f"[{utc_now_iso()}] splitting script by timing")

        split_script_path = work_dir / "split_script.json"

        split_script = split_script_by_timing(
            script=holistic_script,
            keyframes=keyframes,
            timing_plan=timing_plan,
            video_metadata=video_metadata,
            wps=wps,
            min_words=min_words,
            max_words=max_words,
            persist_path=split_script_path,
        )

        holistic_state["split_script"] = split_script.to_dict()
        holistic_state["split_script"]["artifact_path"] = str(split_script_path)
        save_project(data_dir, project_id, proj)

        print(f"[Holistic Pipeline] Split into {len(split_script.sections)} timed sections")

        # Step 5: TTS generation
        print("[Holistic Pipeline] Step 5: Generating TTS audio...")
        append_log(data_dir, project_id, f"[{utc_now_iso()}] generating TTS audio")

        # Convert to segment format for TTS/MUX compatibility
        segments = convert_split_script_to_segments(split_script)

        def process_tts(section) -> tuple[int, dict]:
            section_id = section["id"]
            duration_ms = section["end_ms"] - section["start_ms"]
            wav_path = work_dir / f"section_{section_id}.wav"
            text = section["narration"]["selected_text"]

            tts_result = {}
            try:
                audio_sha, audio_dur = tts_or_silence(
                    text=text,
                    out_path=wav_path,
                    duration_ms=duration_ms,
                    params=tts_params
                )
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
            return section_id, tts_result

        # Parallel TTS generation
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(process_tts, seg): seg for seg in segments}
            for future in as_completed(futures):
                section_id, tts_result = future.result()
                # Find and update the segment
                for seg in segments:
                    if seg["id"] == section_id:
                        seg["tts"] = tts_result
                        break
                print(f"[Holistic Pipeline] TTS complete for section {section_id}")

        # Update holistic state with TTS results
        holistic_state["segments"] = segments
        save_project(data_dir, project_id, proj)

        append_log(data_dir, project_id, f"[{utc_now_iso()}] TTS generation complete")

        # Step 6: Mix and mux
        print("[Holistic Pipeline] Step 6: Mixing and muxing...")
        append_log(data_dir, project_id, f"[{utc_now_iso()}] mixing and muxing")

        # Write SRT
        srt_path = exports_dir / "script_holistic.srt"
        write_srt(segments, srt_path)

        # Collect audio files
        wavs = [Path(seg["tts"]["audio_path"]) for seg in segments if seg["tts"].get("audio_path")]

        # Write filter script and mix
        filter_script = work_dir / "mix_audio_holistic.ffscript"
        write_filter_script(segments, filter_script, total_duration_ms=duration_ms)
        narration_wav = exports_dir / "narration_mix_holistic.wav"
        mix_narration_wav(wavs, filter_script, narration_wav)

        # Mux final video
        final_mp4 = exports_dir / "final_holistic.mp4"
        mux_final_mp4(input_mp4, narration_wav, final_mp4)

        # Attach captions
        final_with_caps = exports_dir / "final_holistic_with_captions.mp4"
        attach_srt_mp4(final_mp4, srt_path, final_with_caps)

        # Update project with exports
        proj["exports"]["artifacts_holistic"] = {
            "script_srt_path": str(srt_path),
            "narration_mix_wav_path": str(narration_wav),
            "final_mp4_path": str(final_mp4),
            "final_mp4_with_captions_path": str(final_with_caps),
        }
        proj["exports"]["ffmpeg_holistic"] = {
            "commands": [
                "holistic_keyframes: ffmpeg -vf select='eq(n,0)' ...",
                f"mix: ffmpeg -filter_complex_script {filter_script} ...",
                "mux: ffmpeg -i input.mp4 -i narration_mix.wav -c:v copy -c:a aac ...",
            ],
            "filter_complex_script_path": str(filter_script)
        }

        holistic_state["status"] = "completed"
        holistic_state["completed_at"] = utc_now_iso()
        proj["exports"]["exported_at"] = utc_now_iso()
        save_project(data_dir, project_id, proj)

        append_log(data_dir, project_id, f"[{utc_now_iso()}] holistic pipeline complete: {final_mp4}")

        print(f"[Holistic Pipeline] Complete: {final_mp4}")

        return {
            "ok": True,
            "project_id": project_id,
            "final_mp4": str(final_mp4),
            "mode": "holistic"
        }

    except Exception as e:
        holistic_state["status"] = "error"
        holistic_state["error"] = str(e)
        holistic_state["failed_at"] = utc_now_iso()
        save_project(data_dir, project_id, proj)
        append_log(data_dir, project_id, f"[{utc_now_iso()}] holistic pipeline error: {e}")
        raise
