#!/usr/bin/env python3
"""
Run segmentation and keyframe extraction only (no vision API call).
This allows us to use MCP for vision analysis separately.
"""
import sys
import json
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.app.config import settings
from backend.app.storage import load_project, save_project, project_dir
from backend.app.pipeline.utils import ffprobe_json
from backend.app.pipeline.segmenter import build_segments
from backend.app.pipeline.keyframes import keyframes_for_segment

def run_segmentation(project_id: str) -> dict:
    """Run segmentation and keyframe extraction, return segments with keyframe paths."""
    data_dir = settings.data_dir
    pdir = project_dir(data_dir, project_id)
    input_mp4 = pdir / "input.mp4"
    work_dir = pdir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    proj = load_project(data_dir, project_id)

    # Get video info
    probe = ffprobe_json(input_mp4)
    fmt = probe.get("format", {})
    duration_s = float(fmt.get("duration") or 0.0)

    seg_cfg = proj["settings"]["segmentation"]
    analysis_fps = int(seg_cfg.get("analysis_fps", 10))
    min_seg_ms = int(seg_cfg.get("min_seg_ms", 2000))
    max_seg_ms = int(seg_cfg.get("max_seg_ms", 8000))

    # Build segments
    proxy_mp4, proxy_sha, segments = build_segments(
        input_mp4=input_mp4,
        work_dir=work_dir,
        duration_s=duration_s,
        analysis_fps=analysis_fps,
        min_seg_ms=min_seg_ms,
        max_seg_ms=max_seg_ms
    )

    # Build segment objects with keyframes
    proj_segments = []
    for seg in segments:
        kfs = keyframes_for_segment(input_mp4, work_dir, seg.id, seg.start_ms, seg.end_ms)
        proj_segments.append({
            "id": seg.id,
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "keyframes": [kf.__dict__ for kf in kfs],
            "vision": {"status": "pending_mcp"},
            "narration": {"target_words": 0, "selected_text": "", "pause_hint_ms": 0, "history": []},
            "tts": {"status": "not_started", "audio_path": "", "attempts": []},
            "mixing": {"timeline_start_ms": seg.start_ms, "gain_db": 0, "fade_in_ms": 10, "fade_out_ms": 30}
        })

    proj["segments"] = proj_segments
    save_project(data_dir, project_id, proj)

    print(f"Segmented into {len(proj_segments)} segments")
    return {"segments": proj_segments, "work_dir": str(work_dir)}


def list_keyframes(project_id: str) -> list:
    """List all keyframe paths for a project."""
    proj = load_project(settings.data_dir, project_id)
    keyframes = []
    for seg in proj.get("segments", []):
        for kf in seg.get("keyframes", []):
            keyframes.append({
                "segment_id": seg["id"],
                "path": kf["path"],
                "timestamp_ms": kf.get("timestamp_ms", 0)
            })
    return keyframes


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python segment_and_keyframes.py <project_id>")
        sys.exit(1)

    project_id = sys.argv[1]
    result = run_segmentation(project_id)

    # Print keyframe paths for MCP analysis
    print("\nKeyframes to analyze:")
    for seg in result["segments"]:
        for kf in seg["keyframes"]:
            print(f"  Seg {seg['id']}: {kf['path']}")
