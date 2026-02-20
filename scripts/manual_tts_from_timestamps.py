from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.config import settings
from backend.app.pipeline.mux import (
    attach_srt_mp4,
    mix_narration_wav,
    mux_final_mp4,
    write_filter_script,
)
from backend.app.pipeline.srt import write_srt
from backend.app.pipeline.tts import tts_or_silence
from backend.app.pipeline.utils import ensure_dir, ffprobe_json


def srt_time_to_ms(t: str) -> int:
    """Convert SRT timestamp HH:MM:SS,mmm to milliseconds."""
    t = t.strip().replace(".", ",")
    parts = t.split(",")
    ms = int(parts[1]) if len(parts) > 1 else 0
    h, m, s = parts[0].split(":")
    return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + ms


def parse_srt(script_path: Path) -> list[tuple[int, int, str]]:
    """Parse SRT file; returns list of (start_ms, end_ms, text)."""
    entries: list[tuple[int, int, str]] = []
    content = script_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", content.strip())
    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        # first line is index number, second is timestamps, rest is text
        m = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", lines[1])
        if not m:
            continue
        start_ms = srt_time_to_ms(m.group(1))
        end_ms = srt_time_to_ms(m.group(2))
        text = " ".join(lines[2:])
        entries.append((start_ms, end_ms, text))
    return entries


def parse_timestamped_script(script_path: Path) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for raw in script_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\[(\d{2}):(\d{2})\]\s*(.+)$", line)
        if not m:
            continue
        mm = int(m.group(1))
        ss = int(m.group(2))
        text = m.group(3).strip()
        start_ms = (mm * 60 + ss) * 1000
        entries.append((start_ms, text))
    return entries


def build_segments(entries: list[tuple[int, str]], video_duration_ms: int) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for i, (start_ms, text) in enumerate(entries):
        if start_ms >= video_duration_ms:
            break
        next_start = entries[i + 1][0] if i + 1 < len(entries) else video_duration_ms
        end_ms = max(start_ms + 500, min(next_start, video_duration_ms))
        if end_ms <= start_ms:
            continue
        segments.append(
            {
                "id": i,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "narration": {"selected_text": text},
                "tts": {"status": "not_started", "audio_path": ""},
            }
        )
    return segments


def main() -> None:
    parser = argparse.ArgumentParser(description="Run manual TTS + mux from [MM:SS] script")
    parser.add_argument("--video", required=True, help="Path to source MP4")
    parser.add_argument("--script", required=True, help="Path to timestamped script txt")
    parser.add_argument("--voice-reference", required=True, help="Path to voice reference wav")
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--output-prefix", default="manual_tts_voiceclone")
    args = parser.parse_args()

    video_path = Path(args.video).resolve()
    script_path = Path(args.script).resolve()
    voice_ref_path = Path(args.voice_reference).resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Missing video: {video_path}")
    if not script_path.exists():
        raise FileNotFoundError(f"Missing script: {script_path}")
    if not voice_ref_path.exists():
        raise FileNotFoundError(f"Missing voice reference: {voice_ref_path}")

    probe = ffprobe_json(video_path)
    video_duration_ms = int(round(float(probe.get("format", {}).get("duration") or 0.0) * 1000))
    if video_duration_ms <= 0:
        raise RuntimeError("Could not determine video duration")

    if script_path.suffix.lower() == ".srt":
        srt_entries = parse_srt(script_path)
        if not srt_entries:
            raise RuntimeError("No entries parsed from SRT file")
        segments = []
        for i, (start_ms, end_ms, text) in enumerate(srt_entries):
            if start_ms >= video_duration_ms:
                break
            end_ms = min(end_ms, video_duration_ms)
            if end_ms <= start_ms:
                end_ms = start_ms + 500
            segments.append({
                "id": i,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "narration": {"selected_text": text},
                "tts": {"status": "not_started", "audio_path": ""},
            })
    else:
        entries = parse_timestamped_script(script_path)
        if not entries:
            raise RuntimeError("No timestamped lines parsed from script")
        segments = build_segments(entries, video_duration_ms)
    if not segments:
        raise RuntimeError("No valid segments produced from script")

    run_id = datetime.now().strftime(f"{args.output_prefix}_%Y%m%d_%H%M%S")
    out_dir = Path(settings.data_dir) / "manual_exports" / run_id
    work_dir = out_dir / "work"
    exports_dir = out_dir / "exports"
    ensure_dir(work_dir)
    ensure_dir(exports_dir)

    tts_params = {
        "audio_prompt_path": str(voice_ref_path),
        "exaggeration": float(args.exaggeration),
        "cfg_weight": float(args.cfg_weight),
    }

    wav_paths: list[Path] = []
    cumulative_audio_ms = 0
    generated_count = 0
    used_segments: list[dict[str, Any]] = []

    # Stop generating new TTS segments once cumulative narration reaches video length.
    for seg in segments:
        if cumulative_audio_ms >= video_duration_ms:
            break

        sid = seg["id"]
        seg_dur = int(seg["end_ms"]) - int(seg["start_ms"])
        remaining_ms = max(1, video_duration_ms - cumulative_audio_ms)
        if seg_dur > remaining_ms:
            seg["end_ms"] = int(seg["start_ms"]) + remaining_ms
            seg_dur = remaining_ms

        wav_path = work_dir / f"seg{sid:03d}.wav"
        audio_sha, audio_dur = tts_or_silence(
            text=seg["narration"]["selected_text"],
            out_path=wav_path,
            duration_ms=seg_dur,
            params=tts_params,
        )
        seg["tts"] = {
            "status": "ok",
            "audio_path": str(wav_path),
            "audio_sha256": audio_sha,
            "audio_duration_ms": audio_dur,
        }
        wav_paths.append(wav_path)
        used_segments.append(seg)
        generated_count += 1
        cumulative_audio_ms += max(0, int(audio_dur))

    srt_path = exports_dir / "script_from_ready_voiceover.srt"
    write_srt(used_segments, srt_path)

    mix_script = work_dir / "mix_audio.ffscript"
    write_filter_script(used_segments, mix_script, total_duration_ms=video_duration_ms)

    narration_wav = exports_dir / "narration_mix.wav"
    mix_narration_wav(wav_paths, mix_script, narration_wav)

    final_mp4 = exports_dir / "final_narrated.mp4"
    mux_final_mp4(video_path, narration_wav, final_mp4)

    final_with_caps = exports_dir / "final_narrated_with_captions.mp4"
    attach_srt_mp4(final_mp4, srt_path, final_with_caps)

    summary = {
        "ok": True,
        "run_id": run_id,
        "video": str(video_path),
        "script": str(script_path),
        "voice_reference": str(voice_ref_path),
        "cfg_weight": float(args.cfg_weight),
        "exaggeration": float(args.exaggeration),
        "video_duration_ms": video_duration_ms,
        "generated_segments": generated_count,
        "cumulative_audio_ms": cumulative_audio_ms,
        "output_dir": str(out_dir),
        "final_mp4": str(final_mp4),
        "final_with_captions": str(final_with_caps),
        "narration_wav": str(narration_wav),
        "srt": str(srt_path),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
