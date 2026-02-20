from __future__ import annotations

from typing import Any


def ensure_tts_profiles(proj: dict[str, Any]) -> dict[str, Any]:
    profiles = proj.get("tts_profiles")
    if not isinstance(profiles, dict):
        profiles = {}
        proj["tts_profiles"] = profiles
    if "default" not in profiles or not isinstance(profiles.get("default"), dict):
        tts_settings = proj.get("settings", {}).get("tts", {}) if isinstance(proj.get("settings"), dict) else {}
        profiles["default"] = {
            "profile_id": "default",
            "display_name": "Default",
            "provider": str(tts_settings.get("provider") or "chatterbox"),
            "endpoint": str(tts_settings.get("endpoint") or ""),
            "voice_mode": str(tts_settings.get("voice_mode") or "predefined_voice"),
            "predefined_voice_id": str(tts_settings.get("predefined_voice_id") or "alloy"),
            "audio_prompt_path": str(tts_settings.get("reference_audio_path") or ""),
            "params": dict(tts_settings.get("default_params") or {}),
        }
    return profiles


def resolve_tts_profile(proj: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
    profiles = ensure_tts_profiles(proj)
    pid = (profile_id or "default").strip() or "default"
    profile = profiles.get(pid)
    if not isinstance(profile, dict):
        raise KeyError(f"Unknown TTS profile: {pid}")
    if not profile.get("profile_id"):
        profile["profile_id"] = pid
    return profile


def upsert_tts_profile(proj: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    profiles = ensure_tts_profiles(proj)
    pid = str(profile.get("profile_id") or "").strip()
    if not pid:
        raise ValueError("profile_id is required")

    existing = profiles.get(pid)
    if not isinstance(existing, dict):
        existing = {"profile_id": pid}
    merged = dict(existing)
    for key in (
        "display_name",
        "provider",
        "endpoint",
        "voice_mode",
        "predefined_voice_id",
        "audio_prompt_path",
    ):
        if key in profile and profile.get(key) is not None:
            merged[key] = profile.get(key)

    params = dict(existing.get("params") or {})
    params.update(dict(profile.get("params") or {}))
    merged["params"] = params
    merged["profile_id"] = pid
    profiles[pid] = merged
    return merged


def resolve_tts_endpoint(
    proj: dict[str, Any],
    profile: dict[str, Any],
    fallback_endpoint: str | None = None,
) -> str:
    endpoint = profile.get("endpoint")
    if isinstance(endpoint, str) and endpoint.strip():
        return endpoint.strip()

    settings_obj = proj.get("settings")
    if isinstance(settings_obj, dict):
        tts_settings = settings_obj.get("tts")
        if isinstance(tts_settings, dict):
            setting_endpoint = tts_settings.get("endpoint")
            if isinstance(setting_endpoint, str) and setting_endpoint.strip():
                return setting_endpoint.strip()

    return (fallback_endpoint or "").strip()


def resolve_tts_params(
    proj: dict[str, Any],
    profile: dict[str, Any],
    params_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    settings_obj = proj.get("settings")
    if isinstance(settings_obj, dict):
        tts_settings = settings_obj.get("tts")
        if isinstance(tts_settings, dict):
            params.update(dict(tts_settings.get("default_params") or {}))

    params.update(dict(profile.get("params") or {}))

    voice_mode = str(profile.get("voice_mode") or "")
    if voice_mode == "reference_audio":
        prompt_path = profile.get("audio_prompt_path")
        if isinstance(prompt_path, str) and prompt_path.strip():
            params["audio_prompt_path"] = prompt_path.strip()
    elif voice_mode == "predefined_voice":
        predefined_voice_id = profile.get("predefined_voice_id")
        if isinstance(predefined_voice_id, str) and predefined_voice_id.strip():
            params["voice"] = predefined_voice_id.strip()

    if params_override:
        params.update(params_override)
    return params
