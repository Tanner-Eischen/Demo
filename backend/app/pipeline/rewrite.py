from __future__ import annotations

import json
from typing import Any

from backend.app.config import settings
from backend.app.pipeline.zai import glm_chat, build_rewrite_messages

def word_count(text: str) -> int:
    return 0 if not text else len([t for t in text.strip().split() if t])

def heuristic_rewrite(candidate: str, target_words: int) -> tuple[str, int, int]:
    # Simple truncate/pad with no filler; returns pause_hint_ms=0
    tokens = [t for t in candidate.strip().split() if t]
    if len(tokens) <= target_words:
        out = " ".join(tokens)
    else:
        out = " ".join(tokens[:target_words])
        # avoid trailing punctuation weirdness
        out = out.rstrip(",;:") 
        if not out.endswith((".", "!", "?")):
            out += "."
    return out, word_count(out), 0

def rewrite_to_fit(segment_id: int, duration_ms: int, target_words: int, candidate: str,
                   on_screen_text: list[str], action_summary: str,
                   project_context: str = "",
                   global_summary: str = "",
                   segment_guidance: dict[str, Any] | None = None,
                   previous_narrations: list[str] | None = None,
                   persist_payload_path: str | None = None,
                   persist_raw_path: str | None = None) -> dict[str, Any]:
    if not settings.zai_api_key:
        narration, wc, pause = heuristic_rewrite(candidate, target_words)
        return {"segment_id": segment_id, "narration": narration, "word_count": wc, "pause_hint_ms": pause}

    messages = build_rewrite_messages(
        segment_id=segment_id,
        duration_ms=duration_ms,
        target_words=target_words,
        candidate=candidate,
        on_screen_text=on_screen_text,
        action_summary=action_summary,
        project_context=project_context,
        global_summary=global_summary,
        segment_guidance=segment_guidance,
        previous_narrations=previous_narrations
    )
    payload = {
        "model": settings.zai_rewrite_model,
        "messages": messages,
        "temperature": 0.3
    }
    if persist_payload_path:
        with open(persist_payload_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    try:
        raw = glm_chat(model=settings.zai_rewrite_model, messages=messages, temperature=0.3)
    except Exception as e:
        print(f"[Rewrite] glm_chat failed for segment {segment_id}: {e}, using heuristic")
        narration, wc, pause = heuristic_rewrite(candidate, target_words)
        return {"segment_id": segment_id, "narration": narration, "word_count": wc, "pause_hint_ms": pause}

    if persist_raw_path:
        with open(persist_raw_path, "w", encoding="utf-8") as f:
            f.write(raw or "")

    # Try to parse JSON, fall back to heuristic
    try:
        data = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        import re
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw or "")
        if match:
            try:
                data = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                data = None
        else:
            data = None

    if not data or not isinstance(data, dict) or not data.get("narration"):
        print(f"[Rewrite] Invalid JSON for segment {segment_id}, using heuristic")
        narration, wc, pause = heuristic_rewrite(candidate, target_words)
        return {"segment_id": segment_id, "narration": narration, "word_count": wc, "pause_hint_ms": pause}

    # basic safety
    data["word_count"] = int(data.get("word_count") or word_count(data.get("narration", "")))
    data["pause_hint_ms"] = int(data.get("pause_hint_ms") or 0)
    return data
