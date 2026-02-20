from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.pipeline.utils import ms_to_srt_time, ensure_dir

def write_srt(segments: list[dict[str, Any]], out_path: Path) -> None:
    ensure_dir(out_path.parent)
    lines: list[str] = []
    idx = 1
    for seg in segments:
        text = (seg.get("narration", {}) or {}).get("selected_text") or ""
        if not text:
            continue
        start_ms = int(seg["start_ms"])
        end_ms = int(seg["end_ms"])
        lines.append(str(idx))
        lines.append(f"{ms_to_srt_time(start_ms)} --> {ms_to_srt_time(end_ms)}")
        lines.append(text)
        lines.append("")  # blank line
        idx += 1
    out_path.write_text("\n".join(lines), encoding="utf-8")
