from __future__ import annotations

from typing import Any

PLAYWRIGHT_OPTIONAL_MODE = "playwright_optional"
PLAYWRIGHT_REQUIRED_MODE = "playwright_required"
DEMO_CAPTURE_EXECUTION_MODES = {
    PLAYWRIGHT_OPTIONAL_MODE,
    PLAYWRIGHT_REQUIRED_MODE,
}


def normalize_demo_capture_execution_mode(
    mode: str | None,
    *,
    default_mode: str = PLAYWRIGHT_OPTIONAL_MODE,
) -> str:
    candidate = str(mode or "").strip().lower()
    if candidate in DEMO_CAPTURE_EXECUTION_MODES:
        return candidate

    normalized_default = str(default_mode or "").strip().lower()
    if normalized_default in DEMO_CAPTURE_EXECUTION_MODES:
        return normalized_default
    return PLAYWRIGHT_OPTIONAL_MODE


def resolve_demo_capture_execution_mode(
    requested_mode: str | None,
    *,
    project_settings: dict[str, Any] | None = None,
    default_mode: str = PLAYWRIGHT_OPTIONAL_MODE,
) -> str:
    if requested_mode is not None:
        return normalize_demo_capture_execution_mode(requested_mode, default_mode=default_mode)

    if isinstance(project_settings, dict):
        from_project = project_settings.get("demo_capture_execution_mode")
        if isinstance(from_project, str) and from_project.strip():
            return normalize_demo_capture_execution_mode(from_project, default_mode=default_mode)

    return normalize_demo_capture_execution_mode(default_mode, default_mode=PLAYWRIGHT_OPTIONAL_MODE)


def _install_hint() -> str:
    return "Install with 'pip install playwright' and 'playwright install chromium'."


def probe_playwright_dependencies() -> dict[str, Any]:
    status: dict[str, Any] = {
        "ok": False,
        "python_package_ok": False,
        "browser_ok": False,
        "error": "",
    }

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        status["error"] = f"Playwright Python package unavailable: {exc}. {_install_hint()}"
        return status

    status["python_package_ok"] = True

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        status["error"] = f"Playwright Chromium launch failed: {exc}. {_install_hint()}"
        return status

    status["browser_ok"] = True
    status["ok"] = True
    return status
