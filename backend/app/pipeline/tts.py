from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from backend.app.config import settings
from backend.app.pipeline.utils import run_cmd, ensure_dir, sha256_file, ffprobe_json
from backend.app.tts.postprocess import postprocess_generated_audio

def probe_audio_duration_ms(path: Path) -> int:
    try:
        data = ffprobe_json(path)
        dur = data.get("format", {}).get("duration")
        if dur is None:
            return 0
        return int(round(float(dur) * 1000))
    except Exception:
        return 0

def trim_audio_to_duration(path: Path, max_ms: int, fade_out_ms: int = 25) -> int:
    if max_ms <= 0:
        max_ms = 1
    max_s = max_ms / 1000.0
    fade_s = max(0.0, min(fade_out_ms / 1000.0, max(0.0, max_s / 2)))
    tmp = path.with_suffix(".trim.wav")
    filters = [f"atrim=end={max_s:.3f}", "asetpts=N/SR/TB"]
    if fade_s > 0:
        start = max(0.0, max_s - fade_s)
        filters.append(f"afade=t=out:d={fade_s:.3f}:st={start:.3f}")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(path),
        "-af", ",".join(filters),
        "-c:a", "pcm_s16le",
        str(tmp)
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg trim audio failed: {err}")
    tmp.replace(path)
    return probe_audio_duration_ms(path)

def generate_silence_wav(out_path: Path, duration_ms: int, sample_rate: int = 48000) -> None:
    ensure_dir(out_path.parent)
    duration_s = max(0.001, duration_ms / 1000.0)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=r={sample_rate}:cl=stereo",
        "-t", f"{duration_s:.3f}",
        "-c:a", "pcm_s16le",
        str(out_path)
    ]
    code, out, err = run_cmd(cmd)
    if code != 0:
        raise RuntimeError(f"ffmpeg silence wav failed: {err}")

def call_tts(
    text: str,
    out_path: Path,
    params: dict[str, Any],
    endpoint: str | None = None,
    mode: str | None = None,
) -> None:
    # Two supported modes:
    # - chatterbox_tts_json: POST JSON to TTS_ENDPOINT, expects audio bytes (wav) as response
    # - openai_audio_speech: OpenAI-like /v1/audio/speech returning audio bytes
    ensure_dir(out_path.parent)

    resolved_endpoint = (endpoint or settings.tts_endpoint or "").strip()
    if not resolved_endpoint:
        raise RuntimeError("TTS_ENDPOINT not set")

    resolved_mode = (mode or settings.tts_mode or "chatterbox_tts_json").strip()

    with httpx.Client(timeout=120) as client:
        if resolved_mode == "chatterbox_tts_json":
            payload = {"text": text, **params}
            r = client.post(resolved_endpoint, json=payload)
            r.raise_for_status()
            out_path.write_bytes(r.content)
        elif resolved_mode == "openai_audio_speech":
            # expects endpoint like http://host/v1/audio/speech
            payload = {
                "model": params.get("model", "tts-1"),
                "voice": params.get("voice", "alloy"),
                "input": text,
                "format": "wav"
            }
            headers = {}
            api_key = params.get("api_key")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            r = client.post(resolved_endpoint, json=payload, headers=headers)
            r.raise_for_status()
            out_path.write_bytes(r.content)
        else:
            raise RuntimeError(f"Unknown TTS_MODE: {resolved_mode}")

def tts_or_silence(
    text: str,
    out_path: Path,
    duration_ms: int,
    params: dict[str, Any],
    endpoint: str | None = None,
    mode: str | None = None,
    postprocess: bool = False,
) -> tuple[str, int]:
    # Returns (sha256, duration_ms_actual_approx). For MVP we don't measure precisely here.
    resolved_endpoint = (endpoint or settings.tts_endpoint or "").strip()
    if resolved_endpoint:
        try:
            call_tts(text=text, out_path=out_path, params=params, endpoint=resolved_endpoint, mode=mode)
            if postprocess:
                postprocess_generated_audio(out_path)
            duration_ms_actual = probe_audio_duration_ms(out_path)
            if duration_ms_actual <= 0:
                raise RuntimeError("Could not probe TTS output duration")
            if duration_ms_actual > duration_ms:
                duration_ms_actual = trim_audio_to_duration(out_path, duration_ms)
            return sha256_file(out_path), duration_ms_actual
        except Exception:
            # fallback to silence if TTS fails
            generate_silence_wav(out_path, duration_ms=duration_ms)
            return sha256_file(out_path), duration_ms
    else:
        generate_silence_wav(out_path, duration_ms=duration_ms)
        return sha256_file(out_path), duration_ms
