from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.pipeline.utils import ensure_dir, run_cmd

def write_filter_script(segments: list[dict[str, Any]], out_path: Path, total_duration_ms: int) -> None:
    ensure_dir(out_path.parent)
    lines = []
    # Inputs are expected to be segment wavs in the same order as segments.
    for i, seg in enumerate(segments):
        delay = int(seg["start_ms"])
        duration_ms = max(1, int(seg["end_ms"]) - int(seg["start_ms"]))
        duration_s = duration_ms / 1000.0
        lines.append(f"[{i}:a]atrim=end={duration_s:.3f},asetpts=N/SR/TB,adelay={delay}|{delay},apad[a{i}];")
    mix_inputs = "".join([f"[a{i}]" for i in range(len(segments))])
    lines.append(f"{mix_inputs}amix=inputs={len(segments)}:dropout_transition=0:normalize=0[aout];")
    end_s = total_duration_ms / 1000.0
    lines.append(f"[aout]atrim=end={end_s:.3f},asetpts=N/SR/TB[narr]")
    out_path.write_text("\n".join(lines), encoding="utf-8")

def mix_narration_wav(segment_wavs: list[Path], filter_script: Path, out_wav: Path) -> None:
    ensure_dir(out_wav.parent)
    cmd = ["ffmpeg", "-y"]
    for wav in segment_wavs:
        cmd += ["-i", str(wav)]
    cmd += [
        "-filter_complex_script", str(filter_script),
        "-map", "[narr]",
        "-ar", "48000", "-ac", "2",
        "-c:a", "pcm_s16le",
        str(out_wav)
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg mix narration failed: {err}")

def mux_final_mp4(input_mp4: Path, narration_wav: Path, out_mp4: Path) -> None:
    ensure_dir(out_mp4.parent)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_mp4),
        "-i", str(narration_wav),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_mp4)
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg mux final failed: {err}")

def attach_srt_mp4(input_mp4: Path, srt_path: Path, out_mp4: Path) -> None:
    ensure_dir(out_mp4.parent)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_mp4),
        "-i", str(srt_path),
        "-c", "copy",
        "-c:s", "mov_text",
        str(out_mp4)
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg attach srt failed: {err}")
