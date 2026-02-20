# GLM-4.6V — Segment Event Extraction Prompt Template

Use with OpenAI-compatible `chat/completions` where `content` can include images:

- Model: `glm-4.6v`
- Provide 2–3 keyframes: start, peak (optional), end
- Force STRICT JSON output.

## System message
You analyze UI demo screenshots. Output must be STRICT JSON only (no markdown) that matches the provided schema.
If uncertain, lower confidence and describe only visible evidence. Never invent UI labels.

## User message (template)
- project_context: {{project_context}} (use only as background context; do not invent labels)
- segment_id: {{segment_id}}
- start_ms: {{start_ms}}
- end_ms: {{end_ms}}

Return ONE JSON object with this exact schema and keys (no extra keys):
```json
{
  "segment_id": {{segment_id}},
  "ui_context": {"app_guess": "", "page_title": "", "primary_region": ""},
  "actions": [
    {"verb":"click|type|scroll|navigate|select|toggle|drag|open|close",
     "target":"",
     "evidence":"(quote exact on-screen text or describe location)",
     "confidence":0.0}
  ],
  "result": "visible outcome",
  "on_screen_text": ["key labels/headings/buttons"],
  "narration_candidates": ["short option 1", "short option 2"]
}
```

Rules:
- Prefer exact strings that appear on screen.
- If no action is visible, return actions as [] and explain in result.
- narration_candidates: short, present tense, action+result, no filler.
- confidence range: 0.0–1.0.
- Never contradict visible evidence from frames.
