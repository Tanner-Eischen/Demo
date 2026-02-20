from __future__ import annotations

from typing import Any

from backend.app.timeline.errors import TimelineImportError


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def normalize_narration_events(
    raw_events: list[dict[str, Any]],
    *,
    video_duration_ms: int | None = None,
    default_duration_ms: int = 3000,
    min_duration_ms: int = 500,
) -> list[dict[str, Any]]:
    if not raw_events:
        return []

    prepared: list[dict[str, Any]] = []
    for idx, event in enumerate(raw_events, start=1):
        if not isinstance(event, dict):
            raise TimelineImportError(message=f"event #{idx} is not an object", code="invalid_event")

        text = str(event.get("text") or "").strip()
        if not text:
            line_no = None
            meta = event.get("meta")
            if isinstance(meta, dict):
                line_no = _as_int(meta.get("source_line"), 0) or None
            raise TimelineImportError(
                message="narration text cannot be empty",
                line_number=line_no,
                code="empty_text",
            )

        prepared.append(
            {
                "raw": event,
                "start_ms": max(0, _as_int(event.get("start_ms"), 0)),
                "end_ms": _as_int(event.get("end_ms"), -1),
                "index": idx,
            }
        )

    prepared.sort(key=lambda item: (item["start_ms"], item["index"]))

    normalized: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    bounded_duration = video_duration_ms if isinstance(video_duration_ms, int) and video_duration_ms > 0 else None

    for idx, item in enumerate(prepared):
        source = item["raw"]
        start_ms = item["start_ms"]
        if bounded_duration is not None and start_ms >= bounded_duration:
            # Skip lines that start after the video duration window.
            continue

        end_ms = item["end_ms"]
        if end_ms <= start_ms:
            next_start = None
            for next_item in prepared[idx + 1 :]:
                if next_item["start_ms"] > start_ms:
                    next_start = next_item["start_ms"]
                    break
            if next_start is not None:
                end_ms = next_start
            else:
                end_ms = start_ms + default_duration_ms

        if bounded_duration is not None and end_ms > bounded_duration:
            end_ms = bounded_duration
        if end_ms <= start_ms:
            end_ms = start_ms + min_duration_ms

        event_id = str(source.get("id") or f"n{idx + 1}")
        if event_id in seen_ids:
            seen_ids[event_id] += 1
            event_id = f"{event_id}_{seen_ids[event_id]}"
        else:
            seen_ids[event_id] = 0

        output_event: dict[str, Any] = {
            "id": event_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": str(source.get("text") or "").strip(),
            "voice_profile_id": str(source.get("voice_profile_id") or "default"),
            "meta": dict(source.get("meta") or {}),
        }
        normalized.append(output_event)

    if not normalized:
        raise TimelineImportError(message="no usable narration events after normalization", code="empty_output")
    return normalized
