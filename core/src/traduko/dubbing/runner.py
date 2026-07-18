"""Dubbing engine runner, executed inside the engine venv.

Speaks JSON lines over stdin/stdout: one request object in, one response
object out, `{"ok": false, "error": ...}` on failure, process stays alive
until stdin closes. Must stay stdlib-only at import time — the heavy
engine imports happen lazily per op so `ping` works before the engine
packages are installed and never loads a model.
"""
from __future__ import annotations

import json
import sys

_diarize_pipeline = None
_diarize_token = None
_tts_model = None


def _dist_version(dist: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(dist)
    except PackageNotFoundError:
        return None


def _ping(req: dict) -> dict:
    info = {
        "ok": True,
        "python": "%d.%d.%d" % sys.version_info[:3],
        "torch": _dist_version("torch"),
        "voxcpm": _dist_version("voxcpm"),
        "pyannote": _dist_version("pyannote.audio"),
        "mps": False,
    }
    if info["torch"]:
        try:
            import torch

            info["mps"] = bool(torch.backends.mps.is_available())
        except Exception:
            pass
    return info


def _diarize(req: dict) -> dict:
    global _diarize_pipeline, _diarize_token
    token = req.get("hf_token") or None
    if _diarize_pipeline is None or _diarize_token != token:
        from pyannote.audio import Pipeline

        _diarize_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1", token=token
        )
        _diarize_token = token
    diarization = _diarize_pipeline(req["audio"])
    segments = [
        {"start": float(turn.start), "end": float(turn.end), "speaker": str(label)}
        for turn, _, label in diarization.itertracks(yield_label=True)
    ]
    return {"ok": True, "segments": segments}


def _synthesize(req: dict) -> dict:
    global _tts_model
    if _tts_model is None:
        from voxcpm import VoxCPM

        _tts_model = VoxCPM.from_pretrained(req.get("model", "openbmb/VoxCPM2"))
    text = req["text"]
    instruction = req.get("instruction")
    if instruction:
        text = f"({instruction}){text}"
    kwargs: dict = {"text": text}
    if req.get("prompt_wav"):
        kwargs["prompt_wav_path"] = req["prompt_wav"]
    if req.get("prompt_text"):
        kwargs["prompt_text"] = req["prompt_text"]
    result = _tts_model.generate(**kwargs)
    if isinstance(result, tuple):
        rate, data = result
    else:
        rate, data = getattr(_tts_model, "sample_rate", 16000), result
    import soundfile

    soundfile.write(req["out"], data, int(rate))
    return {"ok": True, "path": req["out"], "duration": len(data) / float(rate)}


_OPS = {"ping": _ping, "diarize": _diarize, "synthesize": _synthesize}


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            handler = _OPS.get(req.get("op"))
            if handler is None:
                response = {"ok": False, "error": f"unknown op: {req.get('op')}"}
            else:
                response = handler(req)
        except Exception as error:
            response = {"ok": False, "error": str(error)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
