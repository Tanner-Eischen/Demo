"""
Script splitter for the holistic narration pipeline.

Splits the holistic script into timed sections based on vision matching results.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.pipeline.holistic.models import (
    HolisticScript,
    KeyframeMoment,
    SplitScript,
    TimedNarrationSection,
    TimingPlan,
    VideoMetadata,
)
from backend.app.pipeline.utils import atomic_write_json


# Default words per second for timing
DEFAULT_WPS = 2.25

# Minimum gap to fill with silence (ms)
MIN_GAP_MS = 500


def _calculate_section_duration(
    section_text: str,
    wps: float = DEFAULT_WPS,
) -> int:
    """Calculate the duration in ms for a section based on word count."""
    word_count = len(section_text.split())
    duration_s = word_count / wps
    return int(duration_s * 1000)


def _distribute_sections_across_video(
    script: HolisticScript,
    keyframes: list[KeyframeMoment],
    timing_plan: TimingPlan,
    video_metadata: VideoMetadata,
    wps: float = DEFAULT_WPS,
    min_words: int = 4,
    max_words: int = 28,
) -> list[TimedNarrationSection]:
    """
    Distribute sections across the video timeline based on matches.

    This is the core algorithm that:
    1. Uses keyframe matches as anchor points
    2. Distributes sections proportionally between anchors
    3. Handles low-confidence matches with fallback distribution
    """
    timed_sections: list[TimedNarrationSection] = []
    total_duration_ms = video_metadata.duration_ms

    if not script.sections:
        return timed_sections

    # Create a list of (section_index, matched_timestamp_ms, confidence) tuples
    section_matches: list[tuple[int, int, float]] = []

    for section in script.sections:
        match = timing_plan.get_match_for_section(section.section_id)
        if match and match.matched_keyframe_index < len(keyframes):
            keyframe = keyframes[match.matched_keyframe_index]
            section_matches.append((
                section.section_id,
                keyframe.timestamp_ms,
                match.confidence
            ))
        else:
            # Fallback: distribute proportionally
            proportion = section.section_id / max(1, len(script.sections) - 1) if len(script.sections) > 1 else 0.5
            estimated_time = int(proportion * total_duration_ms)
            section_matches.append((
                section.section_id,
                estimated_time,
                0.2  # Low confidence fallback
            ))

    # Sort by matched timestamp
    section_matches.sort(key=lambda x: x[1])

    # Calculate timing for each section
    current_time_ms = 0

    for i, (section_id, matched_time_ms, confidence) in enumerate(section_matches):
        section = next((s for s in script.sections if s.section_id == section_id), None)
        if not section:
            continue

        # Calculate target duration based on word count
        word_count = len(section.text.split())
        target_words = max(min_words, min(max_words, word_count))
        section_duration_ms = _calculate_section_duration(section.text, wps)

        # Determine start time
        if i == 0:
            # First section starts at 0 or matched time, whichever is earlier
            start_ms = min(matched_time_ms, 500)  # Small buffer at start
        else:
            # Subsequent sections: start where previous ended, or at matched time
            # Use the later of the two to avoid overlap
            start_ms = max(current_time_ms, matched_time_ms - (section_duration_ms // 2))

        # Calculate end time
        end_ms = start_ms + section_duration_ms

        # Ensure we don't exceed video duration
        if end_ms > total_duration_ms:
            end_ms = total_duration_ms
            start_ms = max(0, end_ms - section_duration_ms)

        timed_section = TimedNarrationSection(
            section_id=section_id,
            text=section.text,
            start_ms=start_ms,
            end_ms=end_ms,
            target_words=target_words,
            semantic_marker=section.semantic_marker,
            adjusted=False,
        )

        timed_sections.append(timed_section)
        current_time_ms = end_ms

    return timed_sections


def _fill_gaps_with_silence(
    timed_sections: list[TimedNarrationSection],
    total_duration_ms: int,
) -> list[TimedNarrationSection]:
    """
    Identify and mark gaps between sections that may need silence.

    Returns the sections list with potential gap information noted.
    """
    if not timed_sections:
        return timed_sections

    # Sort by start time
    timed_sections.sort(key=lambda s: s.start_ms)
    _ = total_duration_ms  # Reserved for future explicit silence insertion logic.
    return timed_sections


def _light_text_adjustment(
    section: TimedNarrationSection,
    target_duration_ms: int,
    wps: float = DEFAULT_WPS,
    min_words: int = 4,
    max_words: int = 28,
) -> TimedNarrationSection:
    """
    Lightly adjust text if timing is significantly off.

    This is a conservative adjustment that only modifies text if:
    - The section is significantly too long or too short
    - The adjustment is within bounds

    For more significant adjustments, the script should be regenerated.
    """
    current_word_count = section.actual_word_count
    target_word_count = int((target_duration_ms / 1000.0) * wps)
    target_word_count = max(min_words, min(max_words, target_word_count))

    # Only adjust if off by more than 20%
    ratio = current_word_count / target_word_count if target_word_count > 0 else 1.0

    if 0.8 <= ratio <= 1.2:
        # Within acceptable range
        return section

    # For now, we just mark it as needing adjustment but don't modify text
    # Text modification could be added later with an LLM call
    section.adjusted = True
    return section


def split_script_by_timing(
    script: HolisticScript,
    keyframes: list[KeyframeMoment],
    timing_plan: TimingPlan,
    video_metadata: VideoMetadata,
    wps: float = DEFAULT_WPS,
    min_words: int = 4,
    max_words: int = 28,
    persist_path: Path | None = None,
) -> SplitScript:
    """
    Split the holistic script into timed sections based on vision matching.

    Args:
        script: The holistic script to split
        keyframes: List of keyframes used for matching
        timing_plan: The timing plan with section-to-keyframe matches
        video_metadata: Metadata about the video
        wps: Words per second for timing calculations
        min_words: Minimum words per section
        max_words: Maximum words per section
        persist_path: Optional path to save the split script

    Returns:
        SplitScript with timed sections ready for TTS
    """
    split_script = SplitScript(
        sections=[],
        total_duration_ms=video_metadata.duration_ms,
        original_script_text=script.full_text,
    )

    if not script.sections:
        print("[script_splitter] Warning: No sections to split")
        return split_script

    # Distribute sections across the video
    timed_sections = _distribute_sections_across_video(
        script=script,
        keyframes=keyframes,
        timing_plan=timing_plan,
        video_metadata=video_metadata,
        wps=wps,
        min_words=min_words,
        max_words=max_words,
    )

    # Fill gaps with silence markers
    timed_sections = _fill_gaps_with_silence(
        timed_sections=timed_sections,
        total_duration_ms=video_metadata.duration_ms,
    )

    # Check for gaps
    if len(timed_sections) > 1:
        for i in range(1, len(timed_sections)):
            if timed_sections[i].start_ms - timed_sections[i - 1].end_ms > MIN_GAP_MS:
                split_script.has_gaps = True
                break

    # Light text adjustment for timing
    for section in timed_sections:
        adjusted_section = _light_text_adjustment(
            section=section,
            target_duration_ms=section.duration_ms,
            wps=wps,
            min_words=min_words,
            max_words=max_words,
        )
        split_script.sections.append(adjusted_section)

    # Ensure sections cover the full video duration
    if split_script.sections:
        # Adjust first section to start at 0 if it doesn't
        if split_script.sections[0].start_ms > 0:
            split_script.sections[0].start_ms = 0

        # Adjust last section to end at video end if it doesn't
        if split_script.sections[-1].end_ms < video_metadata.duration_ms:
            split_script.sections[-1].end_ms = video_metadata.duration_ms

    # Persist if requested
    if persist_path:
        atomic_write_json(persist_path, split_script.to_dict())

    print(f"[script_splitter] Split into {len(split_script.sections)} timed sections")
    if split_script.has_gaps:
        print("[script_splitter] Note: Gaps detected, silence will be used")

    return split_script


def convert_split_script_to_segments(
    split_script: SplitScript,
) -> list[dict[str, Any]]:
    """
    Convert a SplitScript to the segment format used by TTS and MUX modules.

    This allows the holistic pipeline to reuse existing TTS and MUX infrastructure.

    Args:
        split_script: The split script with timed sections

    Returns:
        List of segment dictionaries compatible with TTS and MUX
    """
    segments = []

    for section in split_script.sections:
        segment = {
            "id": section.section_id,
            "start_ms": section.start_ms,
            "end_ms": section.end_ms,
            "narration": {
                "target_words": section.target_words,
                "selected_text": section.text,
            },
            "tts": {
                "status": "not_started",
                "audio_path": "",
                "attempts": [],
            },
            "mixing": {
                "timeline_start_ms": section.start_ms,
                "gain_db": 0,
                "fade_in_ms": 10,
                "fade_out_ms": 30,
            },
        }
        segments.append(segment)

    return segments
