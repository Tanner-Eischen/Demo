from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TIMELINE_VERSION = "1.0"


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


@dataclass
class NarrationEvent:
    id: str
    start_ms: int
    end_ms: int
    text: str
    voice_profile_id: str = "default"
    meta: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "voice_profile_id": self.voice_profile_id,
        }
        if self.meta:
            data["meta"] = self.meta
        data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NarrationEvent":
        known = {"id", "start_ms", "end_ms", "text", "voice_profile_id", "meta"}
        return cls(
            id=str(data.get("id") or ""),
            start_ms=_to_int(data.get("start_ms"), 0),
            end_ms=_to_int(data.get("end_ms"), 0),
            text=str(data.get("text") or ""),
            voice_profile_id=str(data.get("voice_profile_id") or "default"),
            meta=dict(data.get("meta") or {}),
            extra={k: v for k, v in data.items() if k not in known},
        )


@dataclass
class ActionEvent:
    id: str
    at_ms: int
    action: str
    target: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "at_ms": self.at_ms,
            "action": self.action,
            "args": self.args or {},
        }
        if self.target is not None:
            data["target"] = self.target
        data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionEvent":
        known = {"id", "at_ms", "action", "target", "args"}
        target = data.get("target")
        return cls(
            id=str(data.get("id") or ""),
            at_ms=_to_int(data.get("at_ms"), 0),
            action=str(data.get("action") or ""),
            target=str(target) if target is not None else None,
            args=dict(data.get("args") or {}),
            extra={k: v for k, v in data.items() if k not in known},
        )


@dataclass
class Timeline:
    timeline_version: str = TIMELINE_VERSION
    narration_events: list[NarrationEvent] = field(default_factory=list)
    action_events: list[ActionEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeline_version": self.timeline_version,
            "narration_events": [event.to_dict() for event in self.narration_events],
            "action_events": [event.to_dict() for event in self.action_events],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Timeline":
        return cls(
            timeline_version=str(data.get("timeline_version") or TIMELINE_VERSION),
            narration_events=[
                NarrationEvent.from_dict(item)
                for item in (data.get("narration_events") or [])
                if isinstance(item, dict)
            ],
            action_events=[
                ActionEvent.from_dict(item)
                for item in (data.get("action_events") or [])
                if isinstance(item, dict)
            ],
        )


def empty_timeline() -> dict[str, Any]:
    return Timeline().to_dict()
