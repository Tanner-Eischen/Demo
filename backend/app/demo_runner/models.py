from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DemoActionEvent:
    id: str
    at_ms: int
    action: str
    target: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 10000
    retries: int = 1
    source_index: int = 0


@dataclass
class DemoActionExecution:
    action_id: str
    source_index: int
    action: str
    planned_at_ms: int
    actual_at_ms: int
    drift_ms: int
    timeout_ms: int
    max_retries: int
    attempts: int
    retry_count: int
    status: str
    error: str = ""
    error_type: str = ""
    screenshot_path: str = ""
    attempt_logs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "source_index": self.source_index,
            "action": self.action,
            "planned_at_ms": self.planned_at_ms,
            "actual_at_ms": self.actual_at_ms,
            "drift_ms": self.drift_ms,
            "timeout_ms": self.timeout_ms,
            "max_retries": self.max_retries,
            "attempts": self.attempts,
            "retry_count": self.retry_count,
            "status": self.status,
            "error": self.error,
            "error_type": self.error_type,
            "screenshot_path": self.screenshot_path,
            "attempt_logs": self.attempt_logs,
        }


@dataclass
class DemoRunResult:
    ok: bool
    project_id: str
    mode: str
    run_id: str = ""
    queue_job_id: str | None = None
    execution_mode: str = "playwright_optional"
    raw_demo_mp4: str | None = None
    actions_total: int = 0
    actions_executed: int = 0
    logs_path: str = ""
    artifacts_dir: str = ""
    error: str = ""
    executions: list[DemoActionExecution] = field(default_factory=list)
    stage_timings_ms: dict[str, int] = field(default_factory=dict)
    drift_stats: dict[str, Any] = field(default_factory=dict)
    execution_summary: dict[str, Any] = field(default_factory=dict)
    error_summary: dict[str, Any] = field(default_factory=dict)
    artifact_summary: dict[str, Any] = field(default_factory=dict)
    debug_artifacts: dict[str, Any] = field(default_factory=dict)
    recording_profile: dict[str, Any] = field(default_factory=dict)
    correlation: dict[str, Any] = field(default_factory=dict)
    dependency_status: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_id": self.project_id,
            "mode": self.mode,
            "run_id": self.run_id,
            "queue_job_id": self.queue_job_id,
            "execution_mode": self.execution_mode,
            "raw_demo_mp4": self.raw_demo_mp4,
            "actions_total": self.actions_total,
            "actions_executed": self.actions_executed,
            "logs_path": self.logs_path,
            "artifacts_dir": self.artifacts_dir,
            "error": self.error,
            "executions": [entry.to_dict() for entry in self.executions],
            "stage_timings_ms": self.stage_timings_ms,
            "drift_stats": self.drift_stats,
            "execution_summary": self.execution_summary,
            "error_summary": self.error_summary,
            "artifact_summary": self.artifact_summary,
            "debug_artifacts": self.debug_artifacts,
            "recording_profile": self.recording_profile,
            "correlation": self.correlation,
            "dependency_status": self.dependency_status,
        }
