from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.config import settings
from backend.app.pipeline.zai import build_global_narration_plan_messages, glm_chat

def _coerce_segments_for_llm(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "segment_id": int(seg.get("segment_id", i)) if str(seg.get("segment_id", i)).isdigit() else i,
            "result": seg.get("result", ""),
            "narration_candidates": seg.get("narration_candidates", []),
            "on_screen_text": seg.get("on_screen_text", []),
            "duration_ms": int(seg.get("duration_ms", 0))
        }
        for i, seg in enumerate(segments)
    ]

def _parse_json(raw: str) -> dict[str, Any] | None:
    try:
        return json.loads(raw)
    except Exception:
        pass
    match = re.search(r"```(?:json)?\\s*([\\s\\S]*?)```", raw or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except Exception:
        return None

def _fallback_plan(project_context: str, segments: list[dict[str, Any]]) -> dict[str, Any]:
    summary = project_context.strip() or "Narration should describe the visible demo flow and keep transitions coherent."
    out_segments = []
    for seg in segments:
        sid = int(seg.get("segment_id", len(out_segments)))
        out_segments.append({
            "segment_id": sid,
            "narrative_goal": "",
            "transition_hint": "",
            "must_include_terms": [],
            "preferred_candidate_index": 0
        })
    return {
        "status": "fallback",
        "summary": summary,
        "segments": out_segments
    }

def _normalize_plan(raw: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
    raw_segments = raw.get("segments", [])
    normalized = []
    for seg in _coerce_segments_for_llm(segments):
        sid = int(seg["segment_id"])
        source = {"segment_id": sid, "narrative_goal": "", "transition_hint": "", "must_include_terms": [], "preferred_candidate_index": 0}
        for entry in raw_segments:
            if int(entry.get("segment_id", -1)) == sid:
                preferred = entry.get("preferred_candidate_index", 0)
                try:
                    preferred = int(preferred)
                except Exception:
                    preferred = 0
                max_idx = max(0, len(seg.get("narration_candidates", [])) - 1)
                if preferred < 0 or preferred > max_idx:
                    preferred = 0
                source = {
                    "segment_id": sid,
                    "narrative_goal": str(entry.get("narrative_goal") or ""),
                    "transition_hint": str(entry.get("transition_hint") or ""),
                    "must_include_terms": [str(v) for v in (entry.get("must_include_terms") or []) if isinstance(v, str)],
                    "preferred_candidate_index": preferred
                }
                break
        normalized.append(source)
    return {
        "status": "ok",
        "summary": str(raw.get("summary") or ""),
        "segments": normalized
    }

def plan_global_narration(project_context: str, segments_digest: list[dict[str, Any]],
                          persist_payload_path: Path | None = None,
                          persist_raw_path: Path | None = None) -> dict[str, Any]:
    if not segments_digest:
        return {
            "status": "fallback",
            "summary": (project_context.strip() or "Narration should describe visible actions clearly."),
            "segments": []
        }

    if not settings.zai_api_key:
        return _fallback_plan(project_context, segments_digest)

    messages = build_global_narration_plan_messages(project_context, _coerce_segments_for_llm(segments_digest))
    payload = {
        "model": settings.zai_rewrite_model,
        "messages": messages,
        "temperature": 0.3
    }
    if persist_payload_path:
        persist_payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        raw = glm_chat(model=settings.zai_rewrite_model, messages=messages, temperature=0.3)
        print(f"[GlobalPlanning] Raw response length: {len(raw)}")
    except Exception as e:
        print(f"[GlobalPlanning] glm_chat failed: {e}")
        raise RuntimeError(f"Global narration planning failed (glm_chat error): {e}")
    if persist_raw_path:
        persist_raw_path.write_text(raw, encoding="utf-8")

    parsed = _parse_json(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("summary"), str):
        print(f"[GlobalPlanning] Invalid JSON response: {raw[:500]}")
        raise RuntimeError("Global narration planning failed (invalid JSON response)")
    print(f"[GlobalPlanning] Successfully parsed plan with summary: {parsed.get('summary', '')[:100]}")

    if not isinstance(parsed.get("segments"), list):
        parsed["segments"] = []

    return _normalize_plan(parsed, segments_digest)
