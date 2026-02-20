from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.demo_runner.models import DemoActionEvent

SUPPORTED_ACTIONS = {"goto", "click", "fill", "press", "wait"}
MIN_ACTION_TIMEOUT_MS = 100
MAX_ACTION_TIMEOUT_MS = 120_000
DEFAULT_ACTION_TIMEOUT_MS = 10_000
MIN_ACTION_RETRIES = 0
MAX_ACTION_RETRIES = 3
DEFAULT_ACTION_RETRIES = 1
MAX_WAIT_MS = 120_000


@dataclass
class DemoActionValidationError(ValueError):
    message: str
    index: int | None = None
    action_id: str | None = None

    def __str__(self) -> str:
        parts: list[str] = []
        if self.index is not None:
            parts.append(f"action_index={self.index}")
        if self.action_id:
            parts.append(f"action_id={self.action_id}")
        if parts:
            return f"{self.message} ({', '.join(parts)})"
        return self.message

def _require_target(action: dict[str, Any], idx: int, action_id: str) -> str:
    target = action.get("target")
    if not isinstance(target, str) or not target.strip():
        raise DemoActionValidationError("action requires a non-empty target", index=idx, action_id=action_id)
    return target.strip()


def _parse_int_field(
    value: Any,
    *,
    field_name: str,
    index: int,
    action_id: str,
    minimum: int,
    maximum: int | None = None,
    default: int | None = None,
) -> int:
    if value is None:
        if default is not None:
            return default
        raise DemoActionValidationError(f"{field_name} is required", index=index, action_id=action_id)
    try:
        parsed = int(value)
    except Exception as exc:
        raise DemoActionValidationError(
            f"{field_name} must be an integer",
            index=index,
            action_id=action_id,
        ) from exc
    if parsed < minimum:
        raise DemoActionValidationError(
            f"{field_name} must be >= {minimum}",
            index=index,
            action_id=action_id,
        )
    if maximum is not None and parsed > maximum:
        raise DemoActionValidationError(
            f"{field_name} must be <= {maximum}",
            index=index,
            action_id=action_id,
        )
    return parsed


def parse_action_events(timeline: dict[str, Any]) -> list[DemoActionEvent]:
    raw_actions = timeline.get("action_events")
    if not isinstance(raw_actions, list):
        return []

    parsed: list[DemoActionEvent] = []
    seen_action_ids: set[str] = set()
    for idx, raw in enumerate(raw_actions):
        if not isinstance(raw, dict):
            raise DemoActionValidationError("action event must be an object", index=idx)

        action_id = str(raw.get("id") or f"a{idx + 1}").strip()
        if not action_id:
            raise DemoActionValidationError("action id must be non-empty", index=idx, action_id=action_id)
        if action_id in seen_action_ids:
            raise DemoActionValidationError("duplicate action id", index=idx, action_id=action_id)
        seen_action_ids.add(action_id)

        action_type = str(raw.get("action") or "").strip().lower()
        if action_type not in SUPPORTED_ACTIONS:
            raise DemoActionValidationError(
                f"unsupported action '{action_type or '<empty>'}'",
                index=idx,
                action_id=action_id,
            )

        at_ms = _parse_int_field(
            raw.get("at_ms"),
            field_name="action at_ms",
            index=idx,
            action_id=action_id,
            minimum=0,
        )

        timeout_raw = raw.get("timeout_ms")
        if timeout_raw is None:
            timeout_raw = (raw.get("args") or {}).get("timeout_ms")
        timeout_ms = _parse_int_field(
            timeout_raw,
            field_name="action timeout_ms",
            index=idx,
            action_id=action_id,
            minimum=MIN_ACTION_TIMEOUT_MS,
            maximum=MAX_ACTION_TIMEOUT_MS,
            default=DEFAULT_ACTION_TIMEOUT_MS,
        )

        retries_raw = raw.get("retries")
        if retries_raw is None:
            retries_raw = (raw.get("args") or {}).get("retries")
        retries = _parse_int_field(
            retries_raw,
            field_name="action retries",
            index=idx,
            action_id=action_id,
            minimum=MIN_ACTION_RETRIES,
            maximum=MAX_ACTION_RETRIES,
            default=DEFAULT_ACTION_RETRIES,
        )

        raw_args = raw.get("args")
        if raw_args is None:
            args: dict[str, Any] = {}
        elif not isinstance(raw_args, dict):
            raise DemoActionValidationError("action args must be an object", index=idx, action_id=action_id)
        else:
            args = dict(raw_args)

        target: str | None = None
        if action_type in {"goto", "click", "fill", "press"}:
            target = _require_target(raw, idx, action_id)
        if action_type == "goto" and target is not None and not (
            target.startswith("http://") or target.startswith("https://")
        ):
            raise DemoActionValidationError(
                "goto action target must start with http:// or https://",
                index=idx,
                action_id=action_id,
            )

        if action_type == "fill" and "value" not in args:
            raise DemoActionValidationError("fill action requires args.value", index=idx, action_id=action_id)
        if action_type == "fill":
            fill_value = args.get("value")
            if not isinstance(fill_value, (str, int, float, bool)):
                raise DemoActionValidationError(
                    "fill action args.value must be string/number/bool",
                    index=idx,
                    action_id=action_id,
                )

        if action_type == "press" and "key" not in args:
            raise DemoActionValidationError("press action requires args.key", index=idx, action_id=action_id)
        if action_type == "press":
            key = args.get("key")
            if not isinstance(key, str) or not key.strip():
                raise DemoActionValidationError("press action requires non-empty args.key", index=idx, action_id=action_id)
            args["key"] = key.strip()

        if action_type == "wait":
            wait_ms = _parse_int_field(
                args.get("ms"),
                field_name="wait action args.ms",
                index=idx,
                action_id=action_id,
                minimum=0,
                maximum=MAX_WAIT_MS,
            )
            args["ms"] = wait_ms

        parsed.append(
            DemoActionEvent(
                id=action_id,
                at_ms=at_ms,
                action=action_type,
                target=target,
                args=args,
                timeout_ms=timeout_ms,
                retries=retries,
                source_index=idx,
            )
        )

    parsed.sort(key=lambda event: (event.at_ms, event.source_index, event.id))
    return parsed
