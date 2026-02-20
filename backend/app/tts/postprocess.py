from __future__ import annotations

from pathlib import Path

from backend.app.pipeline.utils import run_cmd


def postprocess_generated_audio(path: Path) -> None:
    """
    Best-effort cleanup pass:
    - remove leading silence
    - normalize loudness for consistent narration levels
    - apply soft limiter to reduce clipping risk
    """
    if not path.exists():
        return

    tmp = path.with_suffix(".post.wav")
    filters = ",".join(
        [
            "silenceremove=start_periods=1:start_duration=0.02:start_threshold=-50dB",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "alimiter=limit=-1.0",
        ]
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-af",
        filters,
        "-c:a",
        "pcm_s16le",
        str(tmp),
    ]
    code, _, _ = run_cmd(cmd)
    if code == 0 and tmp.exists():
        tmp.replace(path)
