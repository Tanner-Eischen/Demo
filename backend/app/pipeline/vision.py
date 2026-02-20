from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import httpx

from backend.app.config import settings


def stub_event(segment_id: int) -> dict[str, Any]:
    return {
        "segment_id": segment_id,
        "ui_context": {"app_guess": "", "page_title": "", "primary_region": ""},
        "actions": [],
        "result": "Unable to infer actions (AI disabled); use narration rewrite or edit manually.",
        "on_screen_text": [],
        "narration_candidates": ["Continue the demo and show the next step.", "Move to the next screen and review the result."]
    }


def analyze_segment(segment_id: int, start_ms: int, end_ms: int, image_urls: list[str],
                    persist_payload_path: Path | None = None,
                    persist_raw_path: Path | None = None,
                    project_context: str = "",
                    use_cache: bool = True) -> dict[str, Any]:
    """
    Analyze a video segment using the Vision MCP Bridge server.
    Falls back to stub if server is unavailable.

    Args:
        use_cache: If True and a cached raw response exists, use it instead of calling API
    """
    if not image_urls:
        return stub_event(segment_id)

    # Check for cached response first
    if use_cache and persist_raw_path and persist_raw_path.exists():
        try:
            cached = json.loads(persist_raw_path.read_text(encoding="utf-8"))
            print(f"[Vision] Using cached response for segment {segment_id}")
            return cached
        except Exception as e:
            print(f"[Vision] Failed to read cache for segment {segment_id}: {e}")

    # Get vision endpoint from settings
    vision_endpoint = getattr(settings, 'vision_endpoint', None) or "http://host.docker.internal:8005"

    # Build payload
    payload = {
        "images": image_urls,
        "segment_id": segment_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "project_context": project_context or ""
    }

    if persist_payload_path:
        persist_payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{vision_endpoint}/analyze-segment",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            result = response.json()

            if persist_raw_path:
                persist_raw_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

            return result

    except Exception as ex:
        # Fallback to stub on error
        error_result = stub_event(segment_id)
        error_result["error"] = str(ex)
        if persist_raw_path:
            persist_raw_path.write_text(json.dumps(error_result, indent=2, ensure_ascii=False), encoding="utf-8")
        return error_result
