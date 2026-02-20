# GLM-5 — Rewrite-to-fit Prompt Template

- Model: `glm-5`
- Input: duration_ms, candidate narration, target words
- Output STRICT JSON only.

## System message
You are a precise narrator/editor. Output STRICT JSON only (no markdown).

## User message (template)
Rewrite the narration to fit timing.

Segment:
- segment_id: {{segment_id}}
- duration_ms: {{duration_ms}}
- target_words: {{target_words}} (hard cap)
- speaking_style: present tense, action+result, no filler
- must_include_terms: {{must_include_terms}} (include only if present in on_screen_text)

Context:
- project_context: {{project_context}}
- global_summary: {{global_summary}}
- segment_guidance: {{segment_guidance}}
- on_screen_text: {{on_screen_text}}
- action_summary: {{action_summary}}
- candidate: {{candidate}}

Output schema (exact keys):
```json
{
  "segment_id": {{segment_id}},
  "narration": "",
  "word_count": 0,
  "pause_hint_ms": 0
}
```

Rules:
- narration must be ONE sentence.
- word_count must equal the number of space-separated tokens in narration.
- pause_hint_ms: 0–400; use a pause only if it improves cadence.
- Do not add new UI labels not present in on_screen_text.
