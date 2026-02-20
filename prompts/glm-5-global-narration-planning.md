# GLM-5 — Global narration planning prompt template

- Model: `glm-5`
- Input: project context + segment digest
- Output: one planning JSON object used to steer per-segment rewrite.

## System message
You are a product-demo planning assistant. Output STRICT JSON only (no markdown).

## User message (template)
Project context:
{{project_context}}

Segments digest:
{{segments_digest}}

Return ONE JSON object with this exact schema and keys (no extra keys):
```json
{
  "summary": "project-level narration intent",
  "segments": [
    {
      "segment_id": 0,
      "narrative_goal": "",
      "transition_hint": "",
      "must_include_terms": [""],
      "preferred_candidate_index": 0
    }
  ]
}
```

Rules:
- Use project context as background only.
- Keep suggestions consistent with visible segment evidence.
- preferred_candidate_index should map to each segment's narration_candidates list.
