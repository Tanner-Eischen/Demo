from __future__ import annotations

import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    redis_url: str = os.getenv("REDIS_URL", "redis://redis:6379/0")
    rq_queue: str = os.getenv("RQ_QUEUE", "default")
    data_dir: str = os.getenv("DATA_DIR", "/data")

    zai_api_key: str | None = os.getenv("ZAI_API_KEY") or None
    zai_base_url: str = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4/")
    zai_vision_model: str = os.getenv("ZAI_VISION_MODEL", "glm-4.6v")
    zai_rewrite_model: str = os.getenv("ZAI_REWRITE_MODEL", "glm-5")

    tts_endpoint: str | None = os.getenv("TTS_ENDPOINT") or None
    tts_mode: str = os.getenv("TTS_MODE", "chatterbox_tts_json")  # chatterbox_tts_json|openai_audio_speech

    # Vision MCP Bridge endpoint (local HTTP server wrapping Z.ai MCP)
    vision_endpoint: str | None = os.getenv("VISION_ENDPOINT") or None

    # Narration pipeline settings
    narration_mode: str = os.getenv("NARRATION_MODE", "tts_only")  # "tts_only" | "unified" | "legacy_segment" | "legacy_holistic"
    demo_capture_execution_mode: str = os.getenv("DEMO_CAPTURE_EXECUTION_MODE", "playwright_optional")  # "playwright_optional" | "playwright_required"
    holistic_keyframe_density: float = float(os.getenv("HOLISTIC_KEYFRAME_DENSITY", "1.0"))
    holistic_match_confidence_threshold: float = float(os.getenv("HOLISTIC_MATCH_CONFIDENCE_THRESHOLD", "0.5"))
    holistic_fallback_to_segment: bool = os.getenv("HOLISTIC_FALLBACK_TO_SEGMENT", "true").lower() == "true"

settings = Settings()
