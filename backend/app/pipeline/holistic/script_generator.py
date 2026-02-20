"""
Script generator for the holistic narration pipeline.

Generates a cohesive narration script from project context and video metadata.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.pipeline.holistic.models import (
    HolisticScript,
    ScriptSection,
    SemanticMarker,
    VideoMetadata,
)
from backend.app.config import settings
from backend.app.pipeline.zai import glm_chat
from backend.app.pipeline.utils import atomic_write_json


def build_holistic_script_messages(
    project_context: str,
    video_metadata: VideoMetadata,
) -> list[dict[str, Any]]:
    """Build the messages for the LLM to generate a holistic script."""
    duration_s = video_metadata.duration_s

    prompt = f"""You are creating a FIRST-PERSON narration script for a software demo video.

PROJECT CONTEXT:
{project_context or "No specific context provided. Create a generic but engaging narration."}

VIDEO METADATA:
- Duration: {duration_s:.1f} seconds
- Estimated scenes: {video_metadata.estimated_scene_count}

TASK: Write a COHESIVE, FLOWING narration script for the entire video. The script should:
1. Flow naturally from beginning to end as ONE continuous narrative
2. Use "I" and "my" language (first-person perspective)
3. Present tense, conversational tone
4. Balance between describing actions AND explaining significance
5. Connect features to problems they solve
6. Mention tech choices when relevant
7. Include brief pauses (marked with [PAUSE]) for natural pacing

STRUCTURE THE SCRIPT INTO LOGICAL SECTIONS:
- intro: Opening that hooks the viewer and states the problem
- feature: Main feature demonstrations
- detail: Technical details or implementation insights
- transition: Brief connectors between topics
- conclusion: Wrap-up and call to action

OUTPUT SCHEMA (strict JSON):
{{
  "full_text": "The complete narration as one flowing piece with [PAUSE] markers",
  "sections": [
    {{
      "section_id": 0,
      "text": "Text for this section",
      "semantic_marker": "intro|feature|detail|transition|conclusion",
      "estimated_duration_ms": 5000
    }}
  ]
}}

RULES:
1. Each section should be 3-10 seconds when spoken (roughly 5-20 words)
2. Mark transitions clearly - don't repeat information
3. The full_text should read naturally when all sections are combined
4. Estimate duration_ms based on word count (~2.25 words per second)
5. No filler phrases like "Let's continue" or "Here we can see"
6. Jump straight into meaningful content
7. Be specific about features and their value

Respond with ONLY valid JSON, no markdown formatting."""

    return [
        {
            "role": "system",
            "content": "You are an expert demo narrator who creates engaging, cohesive scripts. Output STRICT JSON only, no markdown."
        },
        {"role": "user", "content": prompt}
    ]


def generate_holistic_script(
    project_context: str,
    video_metadata: VideoMetadata,
    persist_payload_path: Path | None = None,
    persist_raw_path: Path | None = None,
) -> HolisticScript:
    """
    Generate a cohesive narration script from project context and video metadata.

    Args:
        project_context: The demo context describing the project
        video_metadata: Metadata about the video (duration, etc.)
        persist_payload_path: Optional path to save the request payload
        persist_raw_path: Optional path to save the raw response

    Returns:
        HolisticScript with full text and logical sections
    """
    messages = build_holistic_script_messages(project_context, video_metadata)

    # Persist payload if requested
    if persist_payload_path:
        payload = {
            "model": settings.zai_rewrite_model,
            "messages": messages,
            "temperature": 0.3,
        }
        atomic_write_json(persist_payload_path, payload)

    # Call the LLM, then fall back to a deterministic scaffold if provider calls fail.
    try:
        response_text = glm_chat(
            model=settings.zai_rewrite_model,
            messages=messages,
            temperature=0.3,
            extra_body={"max_tokens": 4096}
        )
    except Exception as exc:
        fallback = _build_fallback_script(project_context, video_metadata)
        response_text = json.dumps(fallback, ensure_ascii=False)
        print(f"[HolisticScript] Model call failed ({exc}); using fallback script")

    # Persist raw response if requested
    if persist_raw_path:
        persist_raw_path.write_text(response_text, encoding="utf-8")

    # Parse the response
    parsed = _parse_script_response(response_text)

    # Create and return the HolisticScript
    script = HolisticScript(
        full_text=parsed.get("full_text", ""),
        project_context_used=project_context,
    )

    # Parse sections
    for section_data in parsed.get("sections", []):
        section = ScriptSection(
            section_id=section_data.get("section_id", len(script.sections)),
            text=section_data.get("text", ""),
            semantic_marker=SemanticMarker(section_data.get("semantic_marker", "feature")),
            estimated_duration_ms=section_data.get("estimated_duration_ms", 0),
        )
        script.sections.append(section)

    # If no sections were parsed, create a single section from full_text
    if not script.sections and script.full_text:
        script.sections.append(ScriptSection(
            section_id=0,
            text=script.full_text,
            semantic_marker=SemanticMarker.FEATURE,
            estimated_duration_ms=int(len(script.full_text.split()) / 2.25 * 1000),
        ))

    return script


def _parse_script_response(response_text: str) -> dict[str, Any]:
    """Parse the LLM response into a structured format."""
    import re

    text = response_text.strip()

    # First, try to extract JSON from markdown code block
    markdown_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if markdown_match:
        json_text = markdown_match.group(1).strip()
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            pass

    # Try direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text (look for the outermost braces)
    # Find the first { and last }
    first_brace = text.find('{')
    last_brace = text.rfind('}')
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        json_candidate = text[first_brace:last_brace + 1]
        try:
            return json.loads(json_candidate)
        except json.JSONDecodeError:
            pass

    # Fallback: treat the entire response as full_text
    return {
        "full_text": response_text,
        "sections": []
    }


def _build_fallback_script(project_context: str, video_metadata: VideoMetadata) -> dict[str, Any]:
    """Create a basic script when upstream text generation is unavailable."""
    context_line = (project_context or "").strip().splitlines()[0] if project_context else ""
    if not context_line:
        context_line = "This walkthrough focuses on the product flow and user outcomes."

    duration_s = max(10.0, video_metadata.duration_s or 30.0)
    section_count = 4 if duration_s < 90 else 5
    base_ms = int((duration_s * 1000) / section_count)

    section_specs: list[tuple[str, str]] = [
        ("intro", f"In this demo, I introduce the workflow and why it matters. {context_line}"),
        ("feature", "I walk through the core interaction and show how the main feature works in practice."),
        ("detail", "I highlight implementation details and explain the technical choices behind this behavior."),
        ("conclusion", "I wrap up the flow, summarize the value, and point to what users can do next."),
    ]
    if section_count == 5:
        section_specs.insert(
            3,
            ("transition", "I connect this step to the next capability so the full story stays coherent."),
        )

    sections: list[dict[str, Any]] = []
    for idx, (marker, text) in enumerate(section_specs):
        sections.append(
            {
                "section_id": idx,
                "text": text,
                "semantic_marker": marker,
                "estimated_duration_ms": base_ms,
            }
        )

    full_text = " [PAUSE] ".join(section["text"] for section in sections)
    return {"full_text": full_text, "sections": sections}
