"""
Data models for the holistic narration pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SemanticMarker(str, Enum):
    """Semantic markers for script sections indicating their role in the narrative."""
    INTRO = "intro"
    FEATURE = "feature"
    DETAIL = "detail"
    TRANSITION = "transition"
    CONCLUSION = "conclusion"


@dataclass
class VideoMetadata:
    """Metadata about the source video."""
    duration_ms: int
    estimated_scene_count: int
    width: int | None = None
    height: int | None = None
    fps: float | None = None

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0


@dataclass
class ScriptSection:
    """A logical section of the holistic script."""
    section_id: int
    text: str
    semantic_marker: SemanticMarker = SemanticMarker.FEATURE
    estimated_duration_ms: int = 0  # Estimated based on word count

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "text": self.text,
            "semantic_marker": self.semantic_marker.value,
            "estimated_duration_ms": self.estimated_duration_ms,
            "word_count": self.word_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScriptSection":
        return cls(
            section_id=data["section_id"],
            text=data["text"],
            semantic_marker=SemanticMarker(data.get("semantic_marker", "feature")),
            estimated_duration_ms=data.get("estimated_duration_ms", 0),
        )


@dataclass
class HolisticScript:
    """The complete cohesive narration script with logical sections."""
    full_text: str
    sections: list[ScriptSection] = field(default_factory=list)
    project_context_used: str = ""

    @property
    def total_word_count(self) -> int:
        return len(self.full_text.split())

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_text": self.full_text,
            "sections": [s.to_dict() for s in self.sections],
            "project_context_used": self.project_context_used,
            "total_word_count": self.total_word_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HolisticScript":
        return cls(
            full_text=data["full_text"],
            sections=[ScriptSection.from_dict(s) for s in data.get("sections", [])],
            project_context_used=data.get("project_context_used", ""),
        )


@dataclass
class KeyframeMoment:
    """A keyframe extracted from the video at a specific timestamp."""
    timestamp_ms: int
    path: str  # Path to the keyframe image file
    visual_signature: str = ""  # Brief description of what's in the frame

    @property
    def timestamp_s(self) -> float:
        return self.timestamp_ms / 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_ms": self.timestamp_ms,
            "path": self.path,
            "visual_signature": self.visual_signature,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeyframeMoment":
        return cls(
            timestamp_ms=data["timestamp_ms"],
            path=data["path"],
            visual_signature=data.get("visual_signature", ""),
        )


@dataclass
class NarrationMatch:
    """A script section matched to a keyframe with confidence score."""
    section_id: int
    matched_keyframe_index: int
    confidence: float  # 0.0 to 1.0
    visual_context: str = ""  # What the vision model saw at this point
    reasoning: str = ""  # Why this match was chosen

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "matched_keyframe_index": self.matched_keyframe_index,
            "confidence": self.confidence,
            "visual_context": self.visual_context,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NarrationMatch":
        return cls(
            section_id=data["section_id"],
            matched_keyframe_index=data["matched_keyframe_index"],
            confidence=data["confidence"],
            visual_context=data.get("visual_context", ""),
            reasoning=data.get("reasoning", ""),
        )


@dataclass
class TimingPlan:
    """Complete timing plan with all section-to-keyframe matches."""
    matches: list[NarrationMatch] = field(default_factory=list)
    unmatched_sections: list[int] = field(default_factory=list)  # section_ids with low confidence
    keyframes_used: list[int] = field(default_factory=list)  # indices of keyframes that got matched

    def get_match_for_section(self, section_id: int) -> NarrationMatch | None:
        for match in self.matches:
            if match.section_id == section_id:
                return match
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": [m.to_dict() for m in self.matches],
            "unmatched_sections": self.unmatched_sections,
            "keyframes_used": self.keyframes_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimingPlan":
        return cls(
            matches=[NarrationMatch.from_dict(m) for m in data.get("matches", [])],
            unmatched_sections=data.get("unmatched_sections", []),
            keyframes_used=data.get("keyframes_used", []),
        )


@dataclass
class TimedNarrationSection:
    """A narration section with precise timing for TTS and mixing."""
    section_id: int
    text: str
    start_ms: int
    end_ms: int
    target_words: int
    semantic_marker: SemanticMarker = SemanticMarker.FEATURE
    adjusted: bool = False  # True if text was adjusted for timing

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000.0

    @property
    def actual_word_count(self) -> int:
        return len(self.text.split())

    @property
    def words_per_second(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        return self.actual_word_count / self.duration_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "target_words": self.target_words,
            "semantic_marker": self.semantic_marker.value,
            "adjusted": self.adjusted,
            "duration_ms": self.duration_ms,
            "actual_word_count": self.actual_word_count,
            "words_per_second": self.words_per_second,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TimedNarrationSection":
        return cls(
            section_id=data["section_id"],
            text=data["text"],
            start_ms=data["start_ms"],
            end_ms=data["end_ms"],
            target_words=data["target_words"],
            semantic_marker=SemanticMarker(data.get("semantic_marker", "feature")),
            adjusted=data.get("adjusted", False),
        )


@dataclass
class SplitScript:
    """Final split script with timed sections ready for TTS."""
    sections: list[TimedNarrationSection] = field(default_factory=list)
    total_duration_ms: int = 0
    has_gaps: bool = False  # True if there are gaps filled with silence
    original_script_text: str = ""

    @property
    def total_word_count(self) -> int:
        return sum(s.actual_word_count for s in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "total_duration_ms": self.total_duration_ms,
            "has_gaps": self.has_gaps,
            "original_script_text": self.original_script_text,
            "total_word_count": self.total_word_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SplitScript":
        return cls(
            sections=[TimedNarrationSection.from_dict(s) for s in data.get("sections", [])],
            total_duration_ms=data.get("total_duration_ms", 0),
            has_gaps=data.get("has_gaps", False),
            original_script_text=data.get("original_script_text", ""),
        )
