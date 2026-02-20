from __future__ import annotations

import re
from typing import Any

from backend.app.timeline.errors import TimelineImportError

_SRT_TS_RE = re.compile(
    r"^(?P<sh>\d{2}):(?P<sm>\d{2}):(?P<ss>\d{2})[,.](?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{2}):(?P<em>\d{2}):(?P<es>\d{2})[,.](?P<ems>\d{3})$"
)


def _srt_time_to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    h = int(hours)
    m = int(minutes)
    s = int(seconds)
    ms = int(millis)
    if m >= 60 or s >= 60:
        raise ValueError("invalid minute/second value")
    return ((h * 3600) + (m * 60) + s) * 1000 + ms


def parse_srt(content: str) -> list[dict[str, Any]]:
    lines = content.splitlines()
    entries: list[dict[str, Any]] = []
    index = 0
    block_idx = 0

    while index < len(lines):
        # Skip leading blank lines between blocks.
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines):
            break

        block_start_line = index + 1
        line = lines[index].strip()

        # Optional numeric SRT index.
        if line.isdigit():
            index += 1
            if index >= len(lines):
                raise TimelineImportError(
                    message="SRT block ended after index without timestamp line",
                    line_number=block_start_line,
                    code="missing_timestamp",
                )
            line = lines[index].strip()

        match = _SRT_TS_RE.match(line)
        if not match:
            raise TimelineImportError(
                message="invalid SRT time range line",
                line_number=index + 1,
                code="invalid_srt_timestamp",
            )

        try:
            start_ms = _srt_time_to_ms(match.group("sh"), match.group("sm"), match.group("ss"), match.group("sms"))
            end_ms = _srt_time_to_ms(match.group("eh"), match.group("em"), match.group("es"), match.group("ems"))
        except ValueError as exc:
            raise TimelineImportError(
                message=str(exc),
                line_number=index + 1,
                code="invalid_srt_timestamp",
            ) from exc

        if end_ms <= start_ms:
            raise TimelineImportError(
                message="SRT end time must be greater than start time",
                line_number=index + 1,
                code="invalid_time_range",
            )

        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1

        if not text_lines:
            raise TimelineImportError(
                message="SRT block is missing narration text",
                line_number=block_start_line,
                code="empty_text",
            )

        block_idx += 1
        entries.append(
            {
                "id": f"n{block_idx}",
                "start_ms": start_ms,
                "end_ms": end_ms,
                "text": " ".join(text_lines),
                "meta": {"source_line": block_start_line, "source_format": "srt"},
            }
        )

    if not entries:
        raise TimelineImportError(message="no subtitle blocks found in SRT", code="empty_input")
    return entries
