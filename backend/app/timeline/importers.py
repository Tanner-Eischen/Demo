from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.timeline.errors import TimelineImportError
from backend.app.timeline.models import NarrationEvent, Timeline
from backend.app.timeline.normalizer import normalize_narration_events
from backend.app.timeline.parsers_srt import parse_srt
from backend.app.timeline.parsers_timestamped_txt import parse_timestamped_txt
from backend.app.timeline.validator import parse_timeline_payload


SUPPORTED_IMPORT_FORMATS = {"auto", "timestamped_txt", "srt", "json"}


def _detect_import_format(content: str, source_name: str | None = None) -> str:
    suffix = Path(source_name or "").suffix.lower()
    if suffix == ".srt":
        return "srt"
    if suffix in {".json", ".timeline"}:
        return "json"
    if suffix in {".txt", ".md"}:
        return "timestamped_txt"

    trimmed = content.lstrip()
    if trimmed.startswith("{"):
        return "json"
    if "-->" in content and ":" in content:
        return "srt"
    return "timestamped_txt"


def _import_json_timeline(content: str) -> Timeline:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise TimelineImportError(
            message=f"invalid JSON timeline payload: {exc.msg}",
            line_number=exc.lineno,
            code="invalid_json",
        ) from exc

    if not isinstance(payload, dict):
        raise TimelineImportError(message="timeline JSON payload must be an object", code="invalid_json_type")
    try:
        return parse_timeline_payload(payload)
    except ValueError as exc:
        raise TimelineImportError(message=str(exc), code="invalid_timeline_schema") from exc


def import_narration_timeline(
    content: str,
    *,
    import_format: str = "auto",
    source_name: str | None = None,
    video_duration_ms: int | None = None,
) -> Timeline:
    fmt = (import_format or "auto").strip().lower()
    if fmt not in SUPPORTED_IMPORT_FORMATS:
        raise TimelineImportError(
            message=f"unsupported import format '{import_format}'",
            code="unsupported_format",
        )
    if fmt == "auto":
        fmt = _detect_import_format(content, source_name)

    if fmt == "json":
        return _import_json_timeline(content)

    if fmt == "srt":
        parsed_events = parse_srt(content)
    elif fmt == "timestamped_txt":
        parsed_events = parse_timestamped_txt(content)
    else:
        raise TimelineImportError(message=f"unsupported import format '{fmt}'", code="unsupported_format")

    normalized_events = normalize_narration_events(parsed_events, video_duration_ms=video_duration_ms)
    return Timeline(
        narration_events=[NarrationEvent.from_dict(event) for event in normalized_events],
        action_events=[],
    )


def import_narration_timeline_dict(
    content: str,
    *,
    import_format: str = "auto",
    source_name: str | None = None,
    video_duration_ms: int | None = None,
) -> dict[str, Any]:
    return import_narration_timeline(
        content,
        import_format=import_format,
        source_name=source_name,
        video_duration_ms=video_duration_ms,
    ).to_dict()
