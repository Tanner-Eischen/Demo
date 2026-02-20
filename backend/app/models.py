from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

DemoCaptureExecutionMode = Literal["playwright_optional", "playwright_required"]
RunType = Literal["render", "demo_capture"]
NarrationMode = Literal[
    "tts_only",
    "timeline",
    "unified",
    "timeline_unified",
    "segment",
    "legacy_segment",
    "holistic",
    "legacy_holistic",
]


class CreateProjectResponse(BaseModel):
    project_id: str

class RunProjectResponse(BaseModel):
    job_id: str
    project_id: Optional[str] = None
    run_type: RunType = "render"
    queue_name: str = "default"
    status_url: str = ""
    queued_at: str = ""
    narration_mode: Optional[str] = None

class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "started", "finished", "failed"]
    result: Optional[Any] = None
    error: Optional[str] = None
    queue_name: Optional[str] = None
    run_type: Optional[RunType] = None
    project_id: Optional[str] = None
    execution_mode: Optional[DemoCaptureExecutionMode] = None
    narration_mode: Optional[str] = None
    enqueued_at: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    queued_at: Optional[str] = None
    func_name: Optional[str] = None


class PatchProjectSettingsRequest(BaseModel):
    demo_context: Optional[str] = None
    demo_capture_execution_mode: Optional[DemoCaptureExecutionMode] = None
    narration_mode: Optional[NarrationMode] = None


class PatchProjectSettingsResponse(BaseModel):
    project_id: str
    demo_context: str
    demo_context_md_path: str
    demo_capture_execution_mode: DemoCaptureExecutionMode
    narration_mode: NarrationMode


class TimelineImportRequest(BaseModel):
    content: str = ""
    import_format: Literal["auto", "timestamped_txt", "srt", "json"] = "auto"
    source_name: Optional[str] = None


class TimelineImportResponse(BaseModel):
    project_id: str
    import_format: str
    narration_event_count: int
    action_event_count: int
    timeline_version: str


class TimelineResponse(BaseModel):
    project_id: str
    timeline: dict[str, Any]


class PatchNarrationEventRequest(BaseModel):
    start_ms: Optional[int] = Field(default=None, ge=0)
    end_ms: Optional[int] = Field(default=None, ge=0)
    text: Optional[str] = None
    voice_profile_id: Optional[str] = None


class PatchNarrationEventResponse(BaseModel):
    project_id: str
    event: dict[str, Any]


class UpsertTTSProfileRequest(BaseModel):
    profile_id: str
    display_name: Optional[str] = None
    provider: Optional[str] = None
    endpoint: Optional[str] = None
    voice_mode: Optional[Literal["predefined_voice", "reference_audio"]] = None
    predefined_voice_id: Optional[str] = None
    audio_prompt_path: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)


class TTSProfileResponse(BaseModel):
    project_id: str
    profile: dict[str, Any]


class TTSPreviewRequest(BaseModel):
    text: str
    duration_ms: int = Field(default=3000, ge=200, le=60000)
    profile_id: str = "default"
    params_override: dict[str, Any] = Field(default_factory=dict)


class TTSPreviewResponse(BaseModel):
    project_id: str
    profile_id: str
    audio_path: str
    audio_sha256: str
    audio_duration_ms: int
    cache_hit: bool = False


class ValidateActionsResponse(BaseModel):
    project_id: str
    action_count: int


class DemoRunQueueResponse(BaseModel):
    project_id: str
    job_id: str
    execution_mode: DemoCaptureExecutionMode
    run_type: RunType = "demo_capture"
    queue_name: str = "default"
    status_url: str = ""
    queued_at: str = ""


class DemoRunsResponse(BaseModel):
    project_id: str
    last_run_id: Optional[str] = None
    run_count: int = 0
    history_limit: int = 0
    runs: list[dict[str, Any]] = Field(default_factory=list)


class RedisDependencyStatus(BaseModel):
    ok: bool
    error: str = ""


class TTSDependencyStatus(BaseModel):
    ok: bool
    endpoint: Optional[str] = None
    error: str = ""


class PlaywrightDependencyStatus(BaseModel):
    ok: bool
    python_package_ok: bool
    browser_ok: bool
    error: str = ""
    execution_mode: DemoCaptureExecutionMode
    required: bool


class HealthDepsResponse(BaseModel):
    ok: bool
    redis: RedisDependencyStatus
    tts: TTSDependencyStatus
    playwright: PlaywrightDependencyStatus
