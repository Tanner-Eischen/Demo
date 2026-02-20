from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from backend.app.timeline.models import Timeline


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[3] / "schemas" / "timeline.schema.json"


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _join_path(parts: list[Any]) -> str:
    if not parts:
        return "$"
    return ".".join(str(part) for part in parts)


def _validate_cross_field_rules(payload: dict[str, Any]) -> None:
    narration_events = payload.get("narration_events") or []
    seen_narration_ids: set[str] = set()
    for idx, event in enumerate(narration_events):
        event_id = str(event.get("id") or "")
        if event_id in seen_narration_ids:
            raise ValueError(f"duplicate narration event id: {event_id}")
        seen_narration_ids.add(event_id)

        start_ms = int(event.get("start_ms") or 0)
        end_ms = int(event.get("end_ms") or 0)
        if end_ms <= start_ms:
            raise ValueError(
                f"narration_events[{idx}] has invalid time range: end_ms ({end_ms}) must be greater than start_ms ({start_ms})"
            )

    action_events = payload.get("action_events") or []
    seen_action_ids: set[str] = set()
    for event in action_events:
        event_id = str(event.get("id") or "")
        if event_id in seen_action_ids:
            raise ValueError(f"duplicate action event id: {event_id}")
        seen_action_ids.add(event_id)


def validate_timeline_payload(payload: dict[str, Any]) -> None:
    errors = sorted(_validator().iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        path = _join_path(list(first.path))
        raise ValueError(f"timeline schema error at {path}: {first.message}")
    _validate_cross_field_rules(payload)


def parse_timeline_payload(payload: dict[str, Any]) -> Timeline:
    validate_timeline_payload(payload)
    return Timeline.from_dict(payload)


def load_timeline(path: str | Path) -> Timeline:
    timeline_path = Path(path)
    payload = json.loads(timeline_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("timeline must be a JSON object")
    return parse_timeline_payload(payload)
