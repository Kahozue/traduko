"""Dubbing engine venv management for settings and preflight.

The engine (voxcpm + pyannote.audio, dragging in torch) is gigabytes we
never bundle into the sidecar; it lives in its own venv under the data
root. VoxCPM requires Python >=3.10 <3.13, so interpreter discovery
filters by version. Installer and probes are injectable so tests never
create real venvs or touch the network.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

ENGINE_PACKAGES = ("voxcpm", "pyannote.audio")
MIN_PYTHON = (3, 10)
MAX_PYTHON_EXCLUSIVE = (3, 13)
_CANDIDATES = ("python3.12", "python3.11", "python3.10", "python3")

VOXCPM_REPO = "openbmb/VoxCPM2"
# Documented size of the public VoxCPM2 weights; used when the hub API is
# unreachable so the settings page still shows a sane estimate.
VOXCPM_KNOWN_MB = 4960.0


def _real_probe(candidate: str) -> tuple[int, int, int] | None:
    executable = candidate if "/" in candidate else shutil.which(candidate)
    if not executable or not Path(executable).exists():
        return None
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    parts = (result.stdout or result.stderr).replace("Python", "").strip().split(".")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (IndexError, ValueError):
        return None


def _compatible(version: tuple[int, int, int] | None) -> bool:
    return version is not None and MIN_PYTHON <= version[:2] < MAX_PYTHON_EXCLUSIVE


def find_python(
    override: str = "",
    probe: Callable[[str], tuple[int, int, int] | None] | None = None,
) -> str | None:
    probe = probe or _real_probe
    for candidate in ((override,) if override else ()) + _CANDIDATES:
        if candidate and _compatible(probe(candidate)):
            return candidate
    return None


def engine_dir(data_root: Path) -> Path:
    return data_root / "engines" / "dubbing"


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _real_install(target_dir: Path, python: str) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = target_dir / "venv"
    subprocess.run([python, "-m", "venv", str(venv_dir)], check=True)
    venv_python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True
    )
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", *ENGINE_PACKAGES], check=True
    )
    (target_dir / ".installed").write_text(
        json.dumps({"packages": list(ENGINE_PACKAGES)}), encoding="utf-8"
    )


def _real_engine_probe(target_dir: Path) -> dict:
    from .client import DubbingEngineClient

    client = DubbingEngineClient(target_dir)
    try:
        return client.ping()
    finally:
        client.close()


def _real_model_download(repo: str) -> None:
    from huggingface_hub import snapshot_download

    snapshot_download(repo)


def _real_model_info(repo: str) -> float:
    """Total weight size in MB from the hub API (public repo, no token)."""
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo, files_metadata=True)
    total = sum(s.size or 0 for s in (info.siblings or []))
    return total / (1024 * 1024)


def _default_model_cache() -> Path:
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        return Path(HF_HUB_CACHE)
    except ImportError:
        return Path.home() / ".cache" / "huggingface" / "hub"


class DubbingManager:
    def __init__(
        self,
        data_root: Path,
        installer: Callable[[Path, str], None] | None = None,
        probe: Callable[[str], tuple[int, int, int] | None] | None = None,
        engine_probe: Callable[[Path], dict] | None = None,
        python_override: str = "",
        model_downloader: Callable[[str], None] | None = None,
        model_info: Callable[[str], float] | None = None,
        model_cache_dir: Path | None = None,
    ) -> None:
        self.data_root = data_root
        self._installer = installer or _real_install
        self._probe = probe
        self._engine_probe = engine_probe or _real_engine_probe
        self.python_override = python_override
        self._lock = threading.Lock()
        self._state = "idle"
        self._error: str | None = None
        self._model_downloader = model_downloader or _real_model_download
        self._model_info = model_info or _real_model_info
        self._model_cache_dir = model_cache_dir
        self._model_state = "idle"
        self._model_error: str | None = None
        self._model_total_mb: float | None = None

    @property
    def engine_dir(self) -> Path:
        return engine_dir(self.data_root)

    def status(self) -> dict:
        target = self.engine_dir
        venv_python = target / "venv" / "bin" / "python"
        with self._lock:
            state, error = self._state, self._error
        return {
            "python": find_python(self.python_override, probe=self._probe) or "",
            "venv": venv_python.exists(),
            "installed": venv_python.exists() and (target / ".installed").exists(),
            "state": state,
            "installing": state == "installing",
            "error": error,
            "installed_mb": round(_dir_size_mb(target), 1),
        }

    def start_install(self) -> bool:
        python = find_python(self.python_override, probe=self._probe)
        with self._lock:
            if self._state == "installing":
                return False
            if python is None:
                self._state = "error"
                self._error = (
                    "no compatible Python found (VoxCPM needs >=3.10 <3.13); "
                    "install one or set dubbing.python in the config"
                )
                return False
            self._state = "installing"
            self._error = None
        thread = threading.Thread(target=self._run, args=(python,), daemon=True)
        thread.start()
        return True

    def _run(self, python: str) -> None:
        try:
            self._installer(self.engine_dir, python)
        except Exception as error:  # surfaced through status, never raised
            with self._lock:
                self._state = "error"
                self._error = str(error)
            return
        with self._lock:
            self._state = "done"

    def test(self) -> dict:
        try:
            return self._engine_probe(self.engine_dir)
        except Exception as error:
            return {"ok": False, "error": str(error)}

    # -- VoxCPM2 weight pre-download ----------------------------------------

    def _model_dir(self) -> Path:
        cache = self._model_cache_dir or _default_model_cache()
        return cache / f"models--{VOXCPM_REPO.replace('/', '--')}"

    def _model_cached(self) -> bool:
        model_dir = self._model_dir()
        snapshots = model_dir / "snapshots"
        if not (snapshots.exists() and any(snapshots.rglob("*"))):
            return False
        blobs = model_dir / "blobs"
        if blobs.exists() and any(blobs.glob("*.incomplete")):
            return False
        return True

    def model_status(self) -> dict:
        with self._lock:
            state, error, total = (
                self._model_state,
                self._model_error,
                self._model_total_mb,
            )
        if total is None:
            try:
                total = self._model_info(VOXCPM_REPO)
            except Exception:  # noqa: BLE001 - offline: fall back to known size
                total = VOXCPM_KNOWN_MB
            with self._lock:
                self._model_total_mb = total
        return {
            "repo": VOXCPM_REPO,
            "total_mb": round(total, 1),
            "downloaded_mb": round(_dir_size_mb(self._model_dir()), 1),
            "cached": self._model_cached(),
            "state": state,
            "downloading": state == "downloading",
            "error": error,
        }

    def start_model_download(self) -> bool:
        with self._lock:
            if self._model_state == "downloading":
                return False
            self._model_state = "downloading"
            self._model_error = None
        thread = threading.Thread(target=self._run_model_download, daemon=True)
        thread.start()
        return True

    def _run_model_download(self) -> None:
        try:
            self._model_downloader(VOXCPM_REPO)
        except Exception as error:  # surfaced through status, never raised
            with self._lock:
                self._model_state = "error"
                self._model_error = str(error)
            return
        with self._lock:
            self._model_state = "done"
