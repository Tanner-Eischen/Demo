from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from backend.app.pipeline.utils import run_cmd, sha256_file, ensure_dir

@dataclass
class Keyframe:
    kind: str  # start|end|peak
    t_ms: int
    path: str
    sha256: str

def extract_frame(input_mp4: Path, t_ms: int, out_path: Path, max_h: int = 720) -> str:
    """Extract a single frame at time t_ms.
    Scales down to max_h to reduce payload size for vision models.
    """
    ensure_dir(out_path.parent)
    t_s = max(0.0, t_ms / 1000.0)
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{t_s:.3f}",
        "-i", str(input_mp4),
        "-vf", f"scale=-2:{max_h}",
        "-frames:v", "1",
        str(out_path)
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg extract frame failed: {err}")
    return sha256_file(out_path)

def keyframes_for_segment(input_mp4: Path, work_dir: Path, seg_id: int, start_ms: int, end_ms: int) -> List[Keyframe]:
    # MVP: start + end (you can add peak later)
    kfs: List[Keyframe] = []
    start_path = work_dir / f"seg{seg_id}_start.png"
    end_path = work_dir / f"seg{seg_id}_end.png"

    # Keep end keyframe safely inside video bounds (at least 100ms before end to avoid ffmpeg issues)
    safe_end_ms = end_ms - 100 if end_ms > start_ms + 100 else start_ms + (end_ms - start_ms) // 2
    kfs.append(Keyframe(kind="start", t_ms=start_ms, path=str(start_path), sha256=extract_frame(input_mp4, start_ms, start_path)))
    kfs.append(Keyframe(kind="end", t_ms=safe_end_ms, path=str(end_path), sha256=extract_frame(input_mp4, safe_end_ms, end_path)))
    return kfs
