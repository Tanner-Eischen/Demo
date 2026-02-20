from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backend.app.pipeline.utils import ensure_dir


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_tts_cache_key(
    *,
    text: str,
    params: dict[str, Any],
    endpoint: str,
    mode: str,
    audio_prompt_path: str | None = None,
    model_signature: str | None = None,
) -> str:
    prompt_sha = None
    if audio_prompt_path:
        p = Path(audio_prompt_path)
        if p.exists() and p.is_file():
            prompt_sha = _sha256_path(p)

    payload = {
        "text": " ".join((text or "").split()),
        "params": params,
        "endpoint": endpoint or "",
        "mode": mode or "",
        "audio_prompt_sha256": prompt_sha,
        "model_signature": model_signature or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def tts_cache_path(cache_dir: Path, cache_key: str) -> Path:
    ensure_dir(cache_dir)
    return cache_dir / f"{cache_key}.wav"


def restore_tts_cache(cache_file: Path, out_file: Path) -> bool:
    if not cache_file.exists():
        return False
    ensure_dir(out_file.parent)
    out_file.write_bytes(cache_file.read_bytes())
    return True


def store_tts_cache(out_file: Path, cache_file: Path) -> None:
    ensure_dir(cache_file.parent)
    if out_file.exists():
        cache_file.write_bytes(out_file.read_bytes())
