"""
Holistic Narration Pipeline

This module implements a holistic approach to narration where the entire
script is generated first as one cohesive piece, then vision matching
connects narration sections to visual moments for timing.
"""

from backend.app.pipeline.holistic.models import (
    VideoMetadata,
    HolisticScript,
    ScriptSection,
    KeyframeMoment,
    NarrationMatch,
    TimingPlan,
    TimedNarrationSection,
    SplitScript,
)
from backend.app.pipeline.holistic.script_generator import generate_holistic_script
from backend.app.pipeline.holistic.timing_matcher import (
    extract_strategic_keyframes,
    match_narration_to_visuals,
)
from backend.app.pipeline.holistic.script_splitter import split_script_by_timing
from backend.app.pipeline.holistic.pipeline import run_holistic_pipeline

__all__ = [
    "VideoMetadata",
    "HolisticScript",
    "ScriptSection",
    "KeyframeMoment",
    "NarrationMatch",
    "TimingPlan",
    "TimedNarrationSection",
    "SplitScript",
    "generate_holistic_script",
    "extract_strategic_keyframes",
    "match_narration_to_visuals",
    "split_script_by_timing",
    "run_holistic_pipeline",
]
