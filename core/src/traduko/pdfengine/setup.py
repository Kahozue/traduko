"""PDF translation engine venv management for settings and stages.

The engine (pdf2zh-next, dragging in BabelDOC / onnxruntime / layout
models) is gigabytes we never bundle into the sidecar; it lives in its
own venv under the data root and is driven by CLI over subprocess so its
AGPL-3.0 licence stays behind the process boundary. pdf2zh-next requires
Python >=3.10 <3.14, so interpreter discovery filters by version.
Installer and probes are injectable so tests never create real venvs or
touch the network.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

ENGINE_PACKAGES = ("pdf2zh-next",)
MIN_PYTHON = (3, 10)
MAX_PYTHON_EXCLUSIVE = (3, 14)
_CANDIDATES = ("python3.13", "python3.12", "python3.11", "python3.10", "python3")


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
    return data_root / "engines" / "pdf"


def venv_python(data_root: Path) -> Path:
    return engine_dir(data_root) / "venv" / "bin" / "python"


def _dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


def _real_install(target_dir: Path, python: str) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    venv_dir = target_dir / "venv"
    subprocess.run([python, "-m", "venv", str(venv_dir)], check=True)
    py = venv_dir / "bin" / "python"
    subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", *ENGINE_PACKAGES], check=True)
    (target_dir / ".installed").write_text(
        json.dumps({"packages": list(ENGINE_PACKAGES)}), encoding="utf-8"
    )


def _real_engine_probe(target_dir: Path) -> dict:
    py = target_dir / "venv" / "bin" / "python"
    try:
        result = subprocess.run(
            [str(py), "-m", "pdf2zh_next", "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "error": str(error)}
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or result.stdout)[:200]}
    return {"ok": True, "version": (result.stdout or result.stderr).strip()}


class PdfManager:
    def __init__(
        self,
        data_root: Path,
        installer: Callable[[Path, str], None] | None = None,
        probe: Callable[[str], tuple[int, int, int] | None] | None = None,
        engine_probe: Callable[[Path], dict] | None = None,
        python_override: str = "",
    ) -> None:
        self.data_root = data_root
        self._installer = installer or _real_install
        self._probe = probe
        self._engine_probe = engine_probe or _real_engine_probe
        self.python_override = python_override
        self._lock = threading.Lock()
        self._state = "idle"
        self._error: str | None = None

    @property
    def engine_dir(self) -> Path:
        return engine_dir(self.data_root)

    def status(self) -> dict:
        target = self.engine_dir
        py = target / "venv" / "bin" / "python"
        with self._lock:
            state, error = self._state, self._error
        return {
            "python": find_python(self.python_override, probe=self._probe) or "",
            "venv": py.exists(),
            "installed": py.exists() and (target / ".installed").exists(),
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
                    "no compatible Python found (pdf2zh-next needs >=3.10 <3.14); "
                    "install one or set pdf.python in the config"
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
