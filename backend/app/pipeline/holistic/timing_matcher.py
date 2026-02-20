"""
Timing matcher for the holistic narration pipeline.

Extracts strategic keyframes from the video and matches narration sections
to keyframes using vision analysis.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

from backend.app.config import settings
from backend.app.pipeline.holistic.models import (
    HolisticScript,
    KeyframeMoment,
    NarrationMatch,
    TimingPlan,
    VideoMetadata,
)
from backend.app.pipeline.utils import ensure_dir, run_cmd, atomic_write_json


# Default density factor: how many keyframes per second of video
DEFAULT_KEYFRAME_DENSITY = 1.0

# Parallel matching workers
MATCHING_BATCH_SIZE = 5


def extract_strategic_keyframes(
    video_path: Path,
    work_dir: Path,
    video_metadata: VideoMetadata,
    density_factor: float = DEFAULT_KEYFRAME_DENSITY,
) -> list[KeyframeMoment]:
    """
    Extract keyframes uniformly distributed across the video.

    Unlike the segment-based approach, this creates a uniform distribution
    of keyframes for matching narration to visuals.

    Args:
        video_path: Path to the input video file
        work_dir: Directory to store extracted keyframes
        video_metadata: Metadata about the video
        density_factor: Keyframes per second (default 1.0)

    Returns:
        List of KeyframeMoment objects
    """
    ensure_dir(work_dir)

    duration_ms = video_metadata.duration_ms
    duration_s = video_metadata.duration_s

    # Calculate number of keyframes based on density
    num_keyframes = max(3, int(duration_s * density_factor))

    # Ensure we don't have too many keyframes for very short videos
    num_keyframes = min(num_keyframes, max(3, int(duration_s * 2)))

    keyframes: list[KeyframeMoment] = []

    for i in range(num_keyframes):
        # Calculate timestamp (skip first and last 5% for cleaner frames)
        margin_ms = int(duration_ms * 0.05)
        usable_duration = duration_ms - (2 * margin_ms)

        if num_keyframes > 1:
            timestamp_ms = margin_ms + int((i / (num_keyframes - 1)) * usable_duration)
        else:
            timestamp_ms = margin_ms + (usable_duration // 2)

        # Extract keyframe image
        keyframe_path = work_dir / f"holistic_kf_{i:03d}.png"
        timestamp_s = timestamp_ms / 1000.0

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{timestamp_s:.3f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(keyframe_path)
        ]

        code, out, err = run_cmd(cmd)
        if code != 0:
            print(f"[timing_matcher] Warning: Failed to extract keyframe at {timestamp_ms}ms: {err}")
            continue

        if not keyframe_path.exists():
            print(f"[timing_matcher] Warning: Keyframe file not created at {timestamp_ms}ms")
            continue

        keyframe = KeyframeMoment(
            timestamp_ms=timestamp_ms,
            path=str(keyframe_path),
            visual_signature=""  # Will be filled during matching
        )
        keyframes.append(keyframe)

    print(f"[timing_matcher] Extracted {len(keyframes)} strategic keyframes")
    return keyframes


def _encode_image_as_data_url(image_path: str) -> str:
    """Encode an image file as a data URL."""
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    image_bytes = path.read_bytes()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _call_match_narration_endpoint(
    narration_text: str,
    keyframe_images: list[str],
    keyframe_times_ms: list[int],
    section_id: int,
    project_context: str = "",
) -> dict[str, Any]:
    """
    Call the vision server's /match-narration endpoint.

    Args:
        narration_text: The text to match
        keyframe_images: List of base64-encoded images (data URLs)
        keyframe_times_ms: List of timestamps for each keyframe
        section_id: The section ID being matched
        project_context: Project context for better matching

    Returns:
        Match result with best_keyframe_index, confidence, etc.
    """
    if not settings.vision_endpoint:
        raise RuntimeError("VISION_ENDPOINT not configured")

    endpoint = f"{settings.vision_endpoint}/match-narration"

    payload = {
        "narration_text": narration_text,
        "keyframe_images": keyframe_images,
        "keyframe_times_ms": keyframe_times_ms,
        "section_id": section_id,
        "project_context": project_context,
    }

    with httpx.Client(timeout=120) as client:
        r = client.post(endpoint, json=payload)
        r.raise_for_status()
        return r.json()


def match_single_section(
    section_id: int,
    narration_text: str,
    keyframes: list[KeyframeMoment],
    project_context: str = "",
    confidence_threshold: float = 0.5,
    max_keyframes: int = 10,  # Limit to avoid payload size issues
) -> NarrationMatch:
    """
    Match a single narration section to the best keyframe.

    Args:
        section_id: The section ID
        narration_text: The narration text to match
        keyframes: List of keyframes to match against
        project_context: Project context for better matching
        confidence_threshold: Minimum confidence for a good match
        max_keyframes: Maximum keyframes to send (to avoid payload limits)

    Returns:
        NarrationMatch with the best match
    """
    # Sample keyframes if we have too many
    if len(keyframes) > max_keyframes:
        # Sample evenly across the video
        step = len(keyframes) / max_keyframes
        sampled_indices = [int(i * step) for i in range(max_keyframes)]
        sampled_keyframes = [keyframes[i] for i in sampled_indices]
    else:
        sampled_keyframes = keyframes
        sampled_indices = list(range(len(keyframes)))

    # Encode keyframes as data URLs
    keyframe_images = []
    keyframe_times_ms = []

    for kf in sampled_keyframes:
        try:
            data_url = _encode_image_as_data_url(kf.path)
            keyframe_images.append(data_url)
            keyframe_times_ms.append(kf.timestamp_ms)
        except Exception as e:
            print(f"[timing_matcher] Warning: Could not encode keyframe {kf.path}: {e}")
            continue

    if not keyframe_images:
        # No valid keyframes - return low confidence match
        return NarrationMatch(
            section_id=section_id,
            matched_keyframe_index=0,
            confidence=0.0,
            visual_context="",
            reasoning="No valid keyframes available"
        )

    try:
        result = _call_match_narration_endpoint(
            narration_text=narration_text,
            keyframe_images=keyframe_images,
            keyframe_times_ms=keyframe_times_ms,
            section_id=section_id,
            project_context=project_context,
        )

        # Map sampled index back to original keyframe index
        sampled_idx = result.get("best_keyframe_index", 0)
        original_idx = sampled_indices[sampled_idx] if sampled_idx < len(sampled_indices) else 0

        match = NarrationMatch(
            section_id=section_id,
            matched_keyframe_index=original_idx,
            confidence=result.get("confidence", 0.3),
            visual_context=result.get("visual_context", ""),
            reasoning=result.get("reasoning", ""),
        )

        # Update keyframe's visual signature if we got context
        if match.visual_context and match.matched_keyframe_index < len(keyframes):
            keyframes[match.matched_keyframe_index].visual_signature = match.visual_context

        return match

    except Exception as e:
        print(f"[timing_matcher] Error matching section {section_id}: {e}")

        # Fallback: Use position-based matching
        # Assign sections proportionally across keyframes
        return NarrationMatch(
            section_id=section_id,
            matched_keyframe_index=0,
            confidence=0.2,
            visual_context="",
            reasoning=f"Vision server error, fallback match: {e}"
        )


def match_narration_to_visuals(
    script: HolisticScript,
    keyframes: list[KeyframeMoment],
    project_context: str = "",
    confidence_threshold: float = 0.5,
    persist_path: Path | None = None,
) -> TimingPlan:
    """
    Match all narration sections to keyframes using vision analysis.

    Args:
        script: The holistic script with sections
        keyframes: List of extracted keyframes
        project_context: Project context for better matching
        confidence_threshold: Minimum confidence for a good match
        persist_path: Optional path to save the timing plan

    Returns:
        TimingPlan with all matches
    """
    timing_plan = TimingPlan()

    if not script.sections:
        print("[timing_matcher] Warning: No sections to match")
        return timing_plan

    if not keyframes:
        print("[timing_matcher] Warning: No keyframes to match against")
        return timing_plan

    print(f"[timing_matcher] Matching {len(script.sections)} sections to {len(keyframes)} keyframes")

    # Process sections in parallel batches
    def process_section(section):
        return match_single_section(
            section_id=section.section_id,
            narration_text=section.text,
            keyframes=keyframes,
            project_context=project_context,
            confidence_threshold=confidence_threshold,
        )

    with ThreadPoolExecutor(max_workers=MATCHING_BATCH_SIZE) as executor:
        futures = {
            executor.submit(process_section, section): section
            for section in script.sections
        }

        for future in as_completed(futures):
            section = futures[future]
            try:
                match = future.result()
                timing_plan.matches.append(match)

                # Track low-confidence matches
                if match.confidence < confidence_threshold:
                    timing_plan.unmatched_sections.append(match.section_id)
                    print(f"[timing_matcher] Low confidence match for section {match.section_id}: {match.confidence:.2f}")
                else:
                    timing_plan.keyframes_used.append(match.matched_keyframe_index)
                    print(f"[timing_matcher] Section {match.section_id} matched to keyframe {match.matched_keyframe_index} (confidence: {match.confidence:.2f})")

            except Exception as e:
                print(f"[timing_matcher] Error processing section {section.section_id}: {e}")
                # Add a fallback match
                fallback_match = NarrationMatch(
                    section_id=section.section_id,
                    matched_keyframe_index=0,
                    confidence=0.1,
                    visual_context="",
                    reasoning=f"Processing error: {e}"
                )
                timing_plan.matches.append(fallback_match)
                timing_plan.unmatched_sections.append(section.section_id)

    # Sort matches by section_id for consistent ordering
    timing_plan.matches.sort(key=lambda m: m.section_id)

    # Persist if requested
    if persist_path:
        atomic_write_json(persist_path, timing_plan.to_dict())

    print(f"[timing_matcher] Matching complete: {len(timing_plan.matches)} matches, {len(timing_plan.unmatched_sections)} low confidence")
    return timing_plan
