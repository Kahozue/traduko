"""faster-whisper engine and model management for settings and preflight.

Model weights live in the Hugging Face hub cache; downloading them is the
heavy step users need visibility into. Download and probe callables are
injectable so tests never touch the network or load a real model.
"""
from __future__ import annotations

import tempfile
import threading
import wave
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path

MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")


def package_available() -> bool:
    return find_spec("faster_whisper") is not None


def hub_cache_dir() -> Path:
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        return Path(HF_HUB_CACHE)
    except ImportError:
        return Path.home() / ".cache" / "huggingface" / "hub"


def model_dir(model_size: str, cache_dir: Path | None = None) -> Path:
    base = cache_dir if cache_dir is not None else hub_cache_dir()
    return base / f"models--Systran--faster-whisper-{model_size}"


def model_cached(model_size: str, cache_dir: Path | None = None) -> bool:
    snapshots = model_dir(model_size, cache_dir) / "snapshots"
    return snapshots.exists() and any(snapshots.rglob("model.bin"))


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _real_download(model_size: str) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(f"Systran/faster-whisper-{model_size}")


def _real_probe(model_size: str) -> dict:
    """Load the model and transcribe half a second of silence."""
    import time

    from faster_whisper import WhisperModel

    started = time.monotonic()
    model = WhisperModel(model_size)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        sample_path = Path(handle.name)
    try:
        with wave.open(str(sample_path), "wb") as sample:
            sample.setnchannels(1)
            sample.setsampwidth(2)
            sample.setframerate(16000)
            sample.writeframes(b"\x00\x00" * 8000)
        segments, info = model.transcribe(str(sample_path))
        list(segments)
    finally:
        sample_path.unlink(missing_ok=True)
    return {"ok": True, "load_seconds": round(time.monotonic() - started, 1)}


class AsrManager:
    def __init__(
        self,
        download: Callable[[str], None] | None = None,
        probe: Callable[[str], dict] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._download = download or _real_download
        self._probe = probe or _real_probe
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._state = "idle"
        self._model: str | None = None
        self._error: str | None = None

    def status(self, model_size: str) -> dict:
        with self._lock:
            state = self._state if self._model in (None, model_size) else "idle"
            error = self._error if self._model == model_size else None
        return {
            "package": package_available(),
            "model": model_size,
            "cached": model_cached(model_size, self.cache_dir),
            "state": state,
            "downloading": state == "downloading",
            "downloaded_mb": round(_dir_size_mb(model_dir(model_size, self.cache_dir)), 1),
            "error": error,
        }

    def start_download(self, model_size: str) -> bool:
        with self._lock:
            if self._state == "downloading":
                return False
            self._state = "downloading"
            self._model = model_size
            self._error = None
        thread = threading.Thread(target=self._run, args=(model_size,), daemon=True)
        thread.start()
        return True

    def _run(self, model_size: str) -> None:
        try:
            self._download(model_size)
        except Exception as error:  # surfaced through status, never raised
            with self._lock:
                self._state = "error"
                self._error = str(error)
            return
        with self._lock:
            self._state = "done"

    def test(self, model_size: str) -> dict:
        try:
            return self._probe(model_size)
        except Exception as error:
            return {"ok": False, "error": str(error)}
