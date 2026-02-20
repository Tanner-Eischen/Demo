"""
Minimal Chatterbox TTS Server for vo-demo-generator
Supports voice cloning with adjustable exaggeration and cfg_weight.

Usage:
  1. Install: pip install -r requirements.txt
  2. Run: python server.py
  3. Test: curl http://localhost:8004/health

Voice Cloning:
  Place a reference audio file (5-10 seconds of your voice) somewhere accessible.
  Then include audio_prompt_path in your TTS params.

Params (passed from vo-demo-generator):
  - text: The text to synthesize (required)
  - audio_prompt_path: Path to voice clone reference WAV (optional, enables cloning)
  - exaggeration: 0.0 - 1.0+ (default 0.5, higher = more expressive/dramatic)
  - cfg_weight: 0.0 - 1.0 (default 0.5, lower = faster speech)
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
import io
import os

app = FastAPI(title="Chatterbox TTS Server")

# Global model instance (loaded on first request)
_model = None
_device = None


def get_model():
    global _model, _device
    if _model is None:
        import torch
        from chatterbox.tts import ChatterboxTTS

        forced_device = (os.getenv("CHATTERBOX_DEVICE") or "").strip().lower()
        if forced_device in {"cpu", "cuda", "mps"}:
            _device = forced_device
        elif torch.cuda.is_available():
            _device = "cuda"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            _device = "mps"  # Apple Silicon
        else:
            _device = "cpu"

        print(f"Loading Chatterbox model on {_device}...")
        _model = ChatterboxTTS.from_pretrained(device=_device)
        print("Model loaded!")
    return _model


class TTSRequest(BaseModel):
    text: str
    audio_prompt_path: Optional[str] = None  # Path to voice clone reference
    exaggeration: float = 0.5  # 0.0 - 1.0+, higher = more expressive
    cfg_weight: float = 0.5    # 0.0 - 1.0, lower = faster speech


@app.post("/tts")
async def tts(req: TTSRequest):
    """Generate TTS audio. Returns WAV bytes."""
    if not req.text:
        raise HTTPException(status_code=400, detail="text is required")

    global _model, _device
    try:
        model = get_model()

        # Build kwargs for generate
        kwargs = {
            "exaggeration": req.exaggeration,
            "cfg_weight": req.cfg_weight,
        }

        # Only add audio_prompt_path if provided and not empty
        if req.audio_prompt_path:
            from pathlib import Path
            prompt_path = Path(req.audio_prompt_path)
            if prompt_path.exists():
                kwargs["audio_prompt_path"] = str(prompt_path)
            else:
                print(f"Warning: audio_prompt_path not found: {req.audio_prompt_path}")

        # Generate audio
        print(f"Generating TTS: text='{req.text[:50]}...' exaggeration={req.exaggeration} cfg={req.cfg_weight}")
        wav = model.generate(req.text, **kwargs)

        # Convert to WAV bytes
        import torchaudio as ta
        buffer = io.BytesIO()
        ta.save(buffer, wav, model.sr, format="wav")
        buffer.seek(0)

        return Response(content=buffer.read(), media_type="audio/wav")
    except Exception as e:
        # Common failure mode on some GPUs: CUDA device-side asserts.
        # Auto-fallback once to CPU so the server returns real audio instead of repeated failures.
        err_text = str(e).lower()
        if "cuda" in err_text and _device == "cuda":
            try:
                from chatterbox.tts import ChatterboxTTS
                print("CUDA generation failed; reloading model on CPU and retrying once...")
                _model = ChatterboxTTS.from_pretrained(device="cpu")
                _device = "cpu"
                wav = _model.generate(req.text, **kwargs)
                import torchaudio as ta
                buffer = io.BytesIO()
                ta.save(buffer, wav, _model.sr, format="wav")
                buffer.seek(0)
                return Response(content=buffer.read(), media_type="audio/wav")
            except Exception as fallback_err:
                e = fallback_err
        import traceback
        error_msg = f"TTS Error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/health")
def health():
    model_status = "loaded" if _model is not None else "not_loaded"
    return {"ok": True, "model": "chatterbox", "status": model_status, "device": _device}


if __name__ == "__main__":
    import uvicorn
    print("Starting Chatterbox TTS Server on http://localhost:8004")
    print("API docs: http://localhost:8004/docs")
    uvicorn.run(app, host="0.0.0.0", port=8004)
