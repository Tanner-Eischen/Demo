"""
Test script for the holistic narration pipeline.

This script tests the holistic pipeline by:
1. Creating a test project from an existing video
2. Configuring it for holistic mode
3. Running the holistic pipeline
4. Reporting results

Usage:
    python test_holistic.py [--project-id PROJECT_ID] [--video VIDEO_PATH]

Options:
    --project-id    Use an existing project ID
    --video         Path to a video file to create a new project
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import shutil
from pathlib import Path
from datetime import datetime, timezone

# Add FFmpeg to PATH if installed via winget
ffmpeg_winget_path = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe" / "ffmpeg-8.0.1-full_build" / "bin"
if ffmpeg_winget_path.exists():
    current_path = os.environ.get("PATH", "")
    if str(ffmpeg_winget_path) not in current_path:
        os.environ["PATH"] = str(ffmpeg_winget_path) + os.pathsep + current_path
        print(f"[Setup] Added FFmpeg to PATH: {ffmpeg_winget_path}")

# Set up environment for local testing
# Use local data directory for testing
local_data_dir = str(Path(__file__).parent / "data")
os.environ.setdefault("DATA_DIR", local_data_dir)
os.environ.setdefault("NARRATION_MODE", "holistic")
os.environ.setdefault("HOLISTIC_KEYFRAME_DENSITY", "0.2")  # 1 keyframe per 5 seconds
os.environ.setdefault("HOLISTIC_MATCH_CONFIDENCE_THRESHOLD", "0.5")
os.environ.setdefault("HOLISTIC_FALLBACK_TO_SEGMENT", "true")

# For local testing, also set Z.ai API key if not set
if not os.environ.get("ZAI_API_KEY"):
    # Try to load from .env file
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and not os.environ.get(key):
                    os.environ[key] = value

# Add backend to path
backend_path = Path(__file__).parent / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path.parent))

from backend.app.config import settings
from backend.app.storage import (
    init_project,
    load_project,
    save_project,
    project_dir,
    ensure_project_defaults,
)
from backend.app.pipeline.utils import sha256_file, ffprobe_json


def create_test_project(video_path: Path, project_id: str) -> dict:
    """Create a new test project from a video file."""
    print(f"\n[1/4] Creating test project: {project_id}")
    print(f"      Video: {video_path}")

    # Get video metadata
    probe = ffprobe_json(video_path)
    duration_s = float(probe.get("format", {}).get("duration") or 0.0)
    duration_ms = int(round(duration_s * 1000))

    width = height = fps = None
    has_audio = False
    for st in probe.get("streams", []):
        if st.get("codec_type") == "video" and width is None:
            width = st.get("width")
            height = st.get("height")
            afr = st.get("avg_frame_rate")
            if isinstance(afr, str) and "/" in afr:
                num, den = afr.split("/", 1)
                try:
                    fps = float(num) / float(den)
                except Exception:
                    fps = None
        if st.get("codec_type") == "audio":
            has_audio = True

    print(f"      Duration: {duration_s:.2f}s ({duration_ms}ms)")
    print(f"      Resolution: {width}x{height}")
    print(f"      FPS: {fps}")
    print(f"      Has audio: {has_audio}")

    # Create project directory
    pdir = project_dir(settings.data_dir, project_id)
    pdir.mkdir(parents=True, exist_ok=True)

    # Copy video to project directory
    input_path = pdir / "input.mp4"
    shutil.copy(video_path, input_path)

    video_sha = sha256_file(input_path)

    # Initialize project
    proj = init_project(
        data_dir=settings.data_dir,
        project_id=project_id,
        video_rel_path=str(input_path),
        video_sha256=video_sha,
        duration_ms=duration_ms,
        width=width,
        height=height,
        fps=fps,
        has_audio=has_audio,
    )

    # Enable holistic mode
    proj["settings"]["narration_mode"] = "holistic"
    proj["settings"]["holistic"]["enabled"] = True
    proj["settings"]["demo_context"] = "This is a test video for the holistic narration pipeline."
    save_project(settings.data_dir, project_id, proj)

    print(f"      Project created: {pdir}")
    return proj


def test_holistic_pipeline(project_id: str) -> dict:
    """Run the holistic pipeline on a project."""
    print(f"\n[2/4] Running holistic pipeline on: {project_id}")

    # Import here to avoid circular imports
    from backend.app.pipeline.holistic.pipeline import run_holistic_pipeline

    try:
        result = run_holistic_pipeline(project_id)
        print(f"      Pipeline completed successfully!")
        print(f"      Result: {json.dumps(result, indent=2)}")
        return result
    except Exception as e:
        print(f"      Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        raise


def verify_results(project_id: str) -> bool:
    """Verify the pipeline results."""
    print(f"\n[3/4] Verifying results...")

    proj = load_project(settings.data_dir, project_id)
    pdir = project_dir(settings.data_dir, project_id)

    success = True

    # Check holistic state
    holistic = proj.get("holistic", {})
    print(f"      Holistic status: {holistic.get('status', 'unknown')}")

    if holistic.get("status") == "completed":
        print(f"      [OK] Pipeline completed")
    else:
        print(f"      [FAIL] Pipeline did not complete")
        success = False

    # Check script generation
    script = holistic.get("script", {})
    if script:
        print(f"      [OK] Script generated: {len(script.get('sections', []))} sections")
        print(f"           Full text length: {len(script.get('full_text', ''))} chars")
    else:
        print(f"      [FAIL] No script generated")
        success = False

    # Check keyframes
    keyframes = holistic.get("keyframes", [])
    if keyframes:
        print(f"      [OK] Keyframes extracted: {len(keyframes)}")
    else:
        print(f"      [FAIL] No keyframes extracted")
        success = False

    # Check timing plan
    timing_plan = holistic.get("timing_plan", {})
    matches = timing_plan.get("matches", [])
    if matches:
        print(f"      [OK] Timing matches: {len(matches)}")
    else:
        print(f"      [FAIL] No timing matches")
        success = False

    # Check exports
    exports = proj.get("exports", {}).get("artifacts_holistic", {})
    if exports:
        print(f"      [OK] Exports created:")
        for key, path in exports.items():
            exists = Path(path).exists() if path else False
            status = "[EXISTS]" if exists else "[MISSING]"
            print(f"           {key}: {path} {status}")
    else:
        print(f"      [FAIL] No exports created")
        success = False

    # Check segment audio files
    segments = holistic.get("segments", [])
    if segments:
        audio_count = sum(1 for s in segments if s.get("tts", {}).get("status") == "ok")
        print(f"      [OK] TTS generated: {audio_count}/{len(segments)} sections")
    else:
        print(f"      [WARN] No segments (TTS might have been skipped)")

    return success


def print_summary(project_id: str, success: bool):
    """Print a summary of the test."""
    print(f"\n[4/4] Test Summary")
    print(f"      Project ID: {project_id}")
    print(f"      Status: {'SUCCESS' if success else 'FAILED'}")

    proj = load_project(settings.data_dir, project_id)

    # Print holistic pipeline details
    holistic = proj.get("holistic", {})
    print(f"\n      Holistic Pipeline Details:")
    print(f"        Status: {holistic.get('status', 'unknown')}")
    print(f"        Started: {holistic.get('started_at', 'N/A')}")
    print(f"        Completed: {holistic.get('completed_at', 'N/A')}")

    if holistic.get("error"):
        print(f"        Error: {holistic.get('error')}")

    # Print script preview
    script = holistic.get("script", {})
    if script.get("full_text"):
        preview = script["full_text"][:200] + "..." if len(script["full_text"]) > 200 else script["full_text"]
        print(f"\n      Script Preview:")
        print(f"        \"{preview}\"")

    # Print timing matches
    timing = holistic.get("timing_plan", {})
    if timing.get("matches"):
        print(f"\n      Timing Matches:")
        for match in timing["matches"][:5]:  # Show first 5
            print(f"        Section {match.get('section_id')}: "
                  f"keyframe {match.get('matched_keyframe_index')}, "
                  f"confidence {match.get('confidence', 0):.2f}")
        if len(timing["matches"]) > 5:
            print(f"        ... and {len(timing['matches']) - 5} more")


def main():
    parser = argparse.ArgumentParser(description="Test the holistic narration pipeline")
    parser.add_argument("--project-id", help="Use an existing project ID")
    parser.add_argument("--video", help="Path to a video file to create a new project")
    parser.add_argument("--skip-run", action="store_true", help="Skip running pipeline, just verify results")
    args = parser.parse_args()

    print("=" * 60)
    print("HOLISTIC NARRATION PIPELINE TEST")
    print("=" * 60)
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"Data dir: {settings.data_dir}")
    print(f"Narration mode: {settings.narration_mode}")

    # Determine project ID
    if args.project_id:
        project_id = args.project_id
        print(f"\nUsing existing project: {project_id}")
    elif args.video:
        video_path = Path(args.video)
        if not video_path.exists():
            print(f"Error: Video file not found: {video_path}")
            sys.exit(1)
        project_id = f"test_holistic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        create_test_project(video_path, project_id)
    else:
        # Use existing test video
        default_video = Path(settings.data_dir) / "video.mp4"
        if default_video.exists():
            project_id = f"test_holistic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            create_test_project(default_video, project_id)
        else:
            # Try to use an existing project
            projects_dir = Path(settings.data_dir) / "projects"
            if projects_dir.exists():
                existing = sorted(projects_dir.glob("proj_*"))
                if existing:
                    project_id = existing[-1].name
                    print(f"\nUsing existing project: {project_id}")

                    # Update to holistic mode
                    proj = load_project(settings.data_dir, project_id)
                    proj["settings"]["narration_mode"] = "holistic"
                    proj["settings"]["holistic"]["enabled"] = True
                    save_project(settings.data_dir, project_id, proj)
                else:
                    print("Error: No test video found and no existing projects")
                    sys.exit(1)
            else:
                print("Error: No test video found at data/video.mp4")
                sys.exit(1)

    # Run pipeline
    if not args.skip_run:
        try:
            test_holistic_pipeline(project_id)
        except Exception as e:
            print(f"\nPipeline failed with error: {e}")
            success = False
            print_summary(project_id, success)
            sys.exit(1)

    # Verify and summarize
    success = verify_results(project_id)
    print_summary(project_id, success)

    print("\n" + "=" * 60)
    if success:
        print("TEST PASSED")
    else:
        print("TEST FAILED")
    print("=" * 60)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
