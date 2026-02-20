from __future__ import annotations

import re
from typing import Any

from backend.app.timeline.errors import TimelineImportError

_TIMESTAMPED_LINE = re.compile(
    r"^\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]\s*(.+?)\s*$"
)


def _to_ms(hours: int, minutes: int, seconds: int) -> int:
    return ((hours * 3600) + (minutes * 60) + seconds) * 1000


def parse_timestamped_txt(content: str) -> list[dict[str, Any]]:
    """
    Parse timestamped narration script lines in one of these formats:
    - [MM:SS] Narration text
    - [HH:MM:SS] Narration text
    """
    entries: list[dict[str, Any]] = []
    for line_no, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        match = _TIMESTAMPED_LINE.match(line)
        if not match:
            raise TimelineImportError(
                message="expected '[MM:SS] text' or '[HH:MM:SS] text'",
                line_number=line_no,
                code="invalid_timestamped_line",
            )

        hh = int(match.group(1) or 0)
        mm = int(match.group(2))
        ss = int(match.group(3))
        text = match.group(4).strip()
        if not text:
            raise TimelineImportError(
                message="timestamped line is missing narration text",
                line_number=line_no,
                code="empty_text",
            )

        if mm >= 60 or ss >= 60:
            raise TimelineImportError(
                message="timestamp has invalid minute/second value",
                line_number=line_no,
                code="invalid_timestamp",
            )

        entries.append(
            {
                "id": f"n{line_no}",
                "start_ms": _to_ms(hh, mm, ss),
                "text": text,
                "meta": {"source_line": line_no, "source_format": "timestamped_txt"},
            }
        )

    if not entries:
        raise TimelineImportError(
            message="no narration lines found in timestamped script",
            code="empty_input",
        )
    return entries
