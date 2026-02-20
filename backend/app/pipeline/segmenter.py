from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

from backend.app.pipeline.utils import run_cmd, sha256_file, ensure_dir

@dataclass
class Segment:
    id: int
    start_ms: int
    end_ms: int

def make_proxy(input_mp4: Path, proxy_mp4: Path, analysis_fps: int = 10, height: int = 540) -> None:
    ensure_dir(proxy_mp4.parent)
    cmd = [
        "ffmpeg", "-y", "-i", str(input_mp4),
        "-vf", f"scale=-2:{height},fps={analysis_fps}",
        "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        str(proxy_mp4)
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg proxy failed: {err}")

def detect_scene_cuts(proxy_mp4: Path, scene_threshold: float = 0.30) -> List[float]:
    # Use ffmpeg scene detection; parse showinfo pts_time.
    # Output lines contain: "pts_time:12.345"
    cmd = [
        "ffmpeg", "-v", "info",
        "-i", str(proxy_mp4),
        "-vf", f"select='gt(scene,{scene_threshold})',showinfo",
        "-f", "null", "-"
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        # ffmpeg writes showinfo to stderr; failure is rare; still raise
        raise RuntimeError(f"ffmpeg scene detect failed: {err}")
    times = []
    for line in err.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            try:
                times.append(float(m.group(1)))
            except ValueError:
                pass
    # de-dup and sort
    times = sorted(set(times))
    return times

def clamp_segments(cuts_s: List[float], duration_s: float, min_ms: int, max_ms: int) -> List[Segment]:
    # Ensure start at 0 and end at duration
    pts = [0.0] + [t for t in cuts_s if 0.0 < t < duration_s] + [duration_s]
    pts = sorted(pts)
    # initial segments
    segs = [(pts[i], pts[i+1]) for i in range(len(pts)-1) if pts[i+1] > pts[i]]
    # Convert to ms
    segs_ms = [[int(round(a*1000)), int(round(b*1000))] for a,b in segs]

    # Merge too-short segments forward
    merged = []
    i = 0
    while i < len(segs_ms):
        s, e = segs_ms[i]
        if (e - s) < min_ms and i < len(segs_ms) - 1:
            # merge into next
            segs_ms[i+1][0] = s
        else:
            merged.append([s, e])
        i += 1

    # Split too-long segments
    final = []
    for s, e in merged:
        length = e - s
        if length <= max_ms:
            final.append([s, e])
            continue
        # split into chunks <= max_ms, but not shorter than min_ms if possible
        n = max(1, int((length + max_ms - 1) // max_ms))
        step = length / n
        cur = s
        for k in range(n):
            nxt = int(round(s + (k+1)*step))
            if k == n-1:
                nxt = e
            final.append([cur, nxt])
            cur = nxt

    # Second pass: merge any trailing short segment
    cleaned = []
    for s, e in final:
        if cleaned and (e - s) < min_ms:
            cleaned[-1][1] = e
        else:
            cleaned.append([s, e])

    return [Segment(id=i, start_ms=s, end_ms=e) for i, (s,e) in enumerate(cleaned)]

def build_segments(input_mp4: Path, work_dir: Path, duration_s: float,
                   analysis_fps: int = 10, min_seg_ms: int = 2000, max_seg_ms: int = 8000) -> tuple[Path, str, List[Segment]]:
    proxy_mp4 = work_dir / "proxy.mp4"
    make_proxy(input_mp4, proxy_mp4, analysis_fps=analysis_fps)
    proxy_sha = sha256_file(proxy_mp4)

    cuts = detect_scene_cuts(proxy_mp4, scene_threshold=0.30)
    segs = clamp_segments(cuts, duration_s=duration_s, min_ms=min_seg_ms, max_ms=max_seg_ms)
    return proxy_mp4, proxy_sha, segs
