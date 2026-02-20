from __future__ import annotations

import json
from typing import Any, List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.app.config import settings

def _endpoint() -> str:
    return settings.zai_base_url.rstrip("/") + "/chat/completions"

def _mcp_bridge_endpoint() -> str | None:
    """Get the MCP bridge endpoint for chat (if configured)"""
    return settings.vision_endpoint

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def glm_chat(model: str, messages: list[dict[str, Any]], temperature: float = 0.2, extra_body: dict[str, Any] | None = None) -> str:
    # For text-only chat, skip MCP bridge and use direct API
    # MCP bridge is mainly for vision tasks
    mcp_endpoint = _mcp_bridge_endpoint()

    # Check if any message has image content - if not, prefer direct API
    has_images = False
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    has_images = True
                    break
        if has_images:
            break

    # Only try MCP bridge for vision requests
    if mcp_endpoint and has_images:
        try:
            payload: dict[str, Any] = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if extra_body and "max_tokens" in extra_body:
                payload["max_tokens"] = extra_body["max_tokens"]

            with httpx.Client(timeout=120) as client:
                r = client.post(f"{mcp_endpoint}/chat", json=payload)
                r.raise_for_status()
                data = r.json()

            return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[zai] MCP bridge chat failed: {e}, falling back to direct API")

    # Fallback to direct REST API
    if not settings.zai_api_key:
        raise RuntimeError("ZAI_API_KEY not set")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if extra_body:
        payload.update(extra_body)

    headers = {"Authorization": f"Bearer {settings.zai_api_key}"}

    with httpx.Client(timeout=300) as client:
        r = client.post(_endpoint(), json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()

    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"Unexpected response shape: {json.dumps(data)[:2000]}")

def build_vision_messages(image_urls: List[str], segment_id: int, start_ms: int, end_ms: int,
                          project_context: str = "") -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    instruction = f"""Project context:
{project_context or ""}

Segment metadata:
- segment_id: {segment_id}
- start_ms: {start_ms}
- end_ms: {end_ms}

Return ONE JSON object with this exact schema and keys (no extra keys):
{{
  "segment_id": {segment_id},
  "ui_context": {{"app_guess": "", "page_title": "", "primary_region": ""}},
  "actions": [
    {{"verb":"click|type|scroll|navigate|select|toggle|drag|open|close",
     "target":"",
     "evidence":"(quote exact on-screen text or describe location)",
     "confidence":0.0}}
  ],
  "result": "visible outcome",
  "on_screen_text": ["key labels/headings/buttons"],
  "narration_candidates": ["short option 1", "short option 2"]
}}

Rules:
- Prefer exact strings that appear on screen.
- If no action is visible, leave actions as an empty array and explain in result.
- narration_candidates must be short, present tense, action+result, no filler.
- confidence range: 0.0–1.0."""
    content.append({"type": "text", "text": instruction})
    return [
        {"role": "system", "content": "You analyze UI demo screenshots. Output must be STRICT JSON only (no markdown) that matches the provided schema. If uncertain, lower confidence and describe only visible evidence. Never invent UI labels."},
        {"role": "user", "content": content}
    ]

def build_global_narration_plan_messages(project_context: str, segments_digest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    instruction = f"""Project context:
{project_context or ""}

Segment digest (for one project, entire timeline):
{json.dumps(segments_digest, ensure_ascii=False, indent=2)}

Return ONE JSON object with this exact schema and keys (no extra keys):
{{
  "summary": "",
  "segments": [
    {{
      "segment_id": 0,
      "narrative_goal": "",
      "transition_hint": "",
      "must_include_terms": [""],
      "preferred_candidate_index": 0
    }}
  ]
}}

Rules:
- Use project context as background only; do not invent actions not visible in frames.
- Stay strictly within segment evidence and do not contradict what the segment vision says.
- preferred_candidate_index must be a valid integer index for that segment's narration_candidates array.
- Keep output STRICT JSON only."""
    return [
        {"role": "system", "content": "You are a planning assistant for demo narration. Output STRICT JSON only (no markdown)."},
        {"role": "user", "content": instruction}
    ]


def build_rewrite_messages(segment_id: int, duration_ms: int, target_words: int, candidate: str,
                           on_screen_text: list[str], action_summary: str,
                           project_context: str = "", global_summary: str = "",
                           segment_guidance: dict[str, Any] | None = None,
                           previous_narrations: list[str] | None = None) -> list[dict[str, Any]]:
    segment_guidance = segment_guidance or {}
    must_include_terms = segment_guidance.get("must_include_terms") or []
    segment_goal = segment_guidance.get("narrative_goal") or ""
    transition_hint = segment_guidance.get("transition_hint") or ""

    # Build previous narrations context to avoid repetition
    prev_context = ""
    if previous_narrations:
        prev_context = f"""
PREVIOUSLY NARRATED (DO NOT REPEAT THESE CONCEPTS):
{chr(10).join(f'- {n}' for n in previous_narrations[-5:])}
"""

    prompt = f"""Rewrite the narration to fit timing while advancing the story.

Segment:
- segment_id: {segment_id}
- duration_ms: {duration_ms}
- target_words: {target_words} (aim for this, slight over/under is ok)
- speaking_style: conversational, present tense

Project Context:
{project_context or "No project context provided"}

Global Story Arc:
{global_summary or "No global summary provided"}

{prev_context}
Segment Guidance:
- narrative_goal: {segment_goal}
- transition_hint: {transition_hint}
- must_include_terms: {json.dumps(must_include_terms, ensure_ascii=False)}

On-Screen Evidence:
- on_screen_text: {json.dumps(on_screen_text, ensure_ascii=False)}
- action_summary: {action_summary}
- raw_candidate: {candidate}

Output schema (exact keys):
{{
  "segment_id": {segment_id},
  "narration": "",
  "word_count": 0,
  "pause_hint_ms": 0
}}

CRITICAL RULES:
1. NARRATIVE STRUCTURE: Follow the story arc - early segments introduce THE PROBLEM, middle segments show THE SOLUTION and HOW IT WORKS, later segments cover TECH DECISIONS and benefits.

2. NO REPETITION: If something was already said in previous narrations, DO NOT say it again. Advance to a NEW point.

3. BE SPECIFIC: Don't say "let me show you the next feature" - instead name the specific feature and WHY it matters. Reference the problem it solves.

4. TECH STACK: When relevant, mention technology choices (React, TypeScript, WebSocket, etc.) and briefly WHY that choice was made.

5. ACTION + IMPACT: Describe what's happening on screen AND the value/benefit. Don't just describe UI actions.

6. NO FILLER: Avoid generic phrases like "Let's continue", "Here we can see", "Now I'll show you". Jump straight into content.

7. word_count must equal the number of space-separated tokens in narration.

8. pause_hint_ms: 0-400; use a pause only if it improves cadence."""
    return [
        {"role": "system", "content": "You are a skilled demo narrator who tells a compelling, non-repetitive story. You connect features to problems they solve. You mention tech choices when relevant. Output STRICT JSON only (no markdown)."},
        {"role": "user", "content": prompt}
    ]
