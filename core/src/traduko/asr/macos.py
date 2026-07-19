"""macOS-native ASR (SpeechAnalyzer) via a compiled Swift helper.

The helper is a single-file Swift CLI compiled on demand with swiftc into
data_root/engines/macos-asr/. It speaks JSON lines on stdout with three
subcommands: probe (capabilities and locales), assets --locale (model
download with progress), transcribe --file --locale (segments). Runs
fully on device; recognizing existing files triggers no permission
prompt (validated on this machine).
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from importlib import resources
from pathlib import Path

from .base import AsrError, AsrResult, AsrSegment, register_asr

HELPER_SOURCE_NAME = "macos_helper.swift"
PROBE_CACHE_SECONDS = 60.0


def helper_dir(data_root: Path) -> Path:
    return data_root / "engines" / "macos-asr"


def helper_binary(data_root: Path) -> Path:
    return helper_dir(data_root) / "helper"


def helper_source_text() -> str:
    return (
        resources.files("traduko.asr").joinpath(HELPER_SOURCE_NAME).read_text("utf-8")
    )


def _real_run(cmd: list[str], timeout: float = 600.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _real_compile(source: Path, output: Path) -> None:
    result = subprocess.run(
        ["swiftc", "-O", "-o", str(output), str(source)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise AsrError(f"swiftc failed: {result.stderr.strip()[:400]}")


class MacosAsrManager:
    """Compile, probe, asset-download and test the helper.

    runner/compiler are injectable so tests never require macOS 26 or
    swiftc; the real paths are exercised in the machine validation step.
    """

    def __init__(
        self,
        data_root: Path,
        *,
        runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
        compiler: Callable[[Path, Path], None] | None = None,
        platform_system: str | None = None,
    ) -> None:
        self.data_root = data_root
        self._runner = runner or _real_run
        self._compiler = compiler or _real_compile
        self._system = platform_system or platform.system()
        self._lock = threading.Lock()
        self._probe_cache: tuple[float, dict] | None = None
        self._assets_state = "idle"
        self._assets_progress = 0.0
        self._assets_error: str | None = None

    # -- compilation ---------------------------------------------------------

    def ensure_compiled(self) -> tuple[bool, str]:
        if self._system != "Darwin":
            return False, "macOS only"
        if shutil.which("swiftc") is None and self._compiler is _real_compile:
            return False, "swiftc not found (install the Xcode command line tools)"
        source_text = helper_source_text()
        digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        directory = helper_dir(self.data_root)
        binary = helper_binary(self.data_root)
        stamp = directory / ".source-hash"
        if binary.exists() and stamp.exists() and stamp.read_text().strip() == digest:
            return True, ""
        directory.mkdir(parents=True, exist_ok=True)
        source_path = directory / HELPER_SOURCE_NAME
        source_path.write_text(source_text, encoding="utf-8")
        try:
            self._compiler(source_path, binary)
        except AsrError as error:
            return False, str(error)
        stamp.write_text(digest, encoding="utf-8")
        # A rebuilt helper invalidates any cached probe result.
        self._probe_cache = None
        return True, ""

    # -- probing -------------------------------------------------------------

    def probe(self) -> dict:
        ok, error = self.ensure_compiled()
        if not ok:
            return {"available": False, "os_ok": False, "error": error}
        try:
            result = self._runner([str(helper_binary(self.data_root)), "probe"])
        except Exception as error:  # noqa: BLE001 - surfaced in status
            return {"available": False, "os_ok": False, "error": str(error)}
        if result.returncode != 0:
            return {
                "available": False,
                "os_ok": False,
                "error": (result.stderr or result.stdout or "probe failed")[:400],
            }
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "available" in payload:
                return payload
        return {"available": False, "os_ok": False, "error": "no probe output"}

    def status(self) -> dict:
        with self._lock:
            cached = self._probe_cache
            if cached and time.monotonic() - cached[0] < PROBE_CACHE_SECONDS:
                probe = cached[1]
            else:
                probe = None
        if probe is None:
            probe = self.probe()
            with self._lock:
                self._probe_cache = (time.monotonic(), probe)
        with self._lock:
            assets_state = self._assets_state
            assets_progress = self._assets_progress
            assets_error = self._assets_error
        return {
            "platform_ok": self._system == "Darwin",
            "available": bool(probe.get("available")),
            "os_ok": bool(probe.get("os_ok")),
            "transcriber_locales": probe.get("transcriber_locales", []),
            "dictation_locales": probe.get("dictation_locales", []),
            "installed_locales": probe.get("installed", []),
            "assets_state": assets_state,
            "assets_progress": assets_progress,
            "assets_error": assets_error,
            "error": probe.get("error"),
        }

    # -- assets --------------------------------------------------------------

    def start_assets(self, locale: str) -> bool:
        with self._lock:
            if self._assets_state == "downloading":
                return False
            self._assets_state = "downloading"
            self._assets_progress = 0.0
            self._assets_error = None
        thread = threading.Thread(target=self._run_assets, args=(locale,), daemon=True)
        thread.start()
        return True

    def _run_assets(self, locale: str) -> None:
        try:
            result = self._runner(
                [str(helper_binary(self.data_root)), "assets", "--locale", locale]
            )
        except Exception as error:  # noqa: BLE001
            with self._lock:
                self._assets_state = "error"
                self._assets_error = str(error)
            return
        error_text: str | None = None
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "progress" in payload:
                with self._lock:
                    self._assets_progress = float(payload["progress"])
            if payload.get("error"):
                error_text = str(payload["error"])
        with self._lock:
            if result.returncode != 0 or error_text:
                self._assets_state = "error"
                self._assets_error = error_text or (result.stderr or "")[:400]
            else:
                self._assets_state = "done"
                self._assets_progress = 1.0
            self._probe_cache = None

    def test(self, locale: str = "") -> dict:
        status = self.status()
        if not status["available"]:
            return {"ok": False, "error": status.get("error") or "unavailable"}
        return {
            "ok": True,
            "locales": len(status["transcriber_locales"]),
            "installed": status["installed_locales"],
        }


@register_asr("macos_native")
class MacosNativeProvider:
    def __init__(
        self,
        locale: str = "",
        data_root: str = "",
        runner: Callable[..., subprocess.Popen] | None = None,
    ) -> None:
        self.locale = locale
        self.data_root = Path(data_root) if data_root else None
        self._popen = runner or subprocess.Popen

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float, float], None] | None = None,
        glossary_terms: list[str] | None = None,
    ) -> AsrResult:
        if self.data_root is None:
            raise AsrError("macos_native requires a data_root")
        binary = helper_binary(self.data_root)
        if not binary.exists():
            raise AsrError(
                "macOS speech helper is not compiled; open the settings "
                "speech-recognition section to set it up"
            )
        locale = self.locale or (language or "")
        cmd = [str(binary), "transcribe", "--file", str(audio_path)]
        if locale:
            cmd += ["--locale", locale]
        if glossary_terms:
            cmd += ["--contextual-strings", "\x1f".join(glossary_terms)]
        try:
            total = 0.0
            from ..media import probe_duration

            try:
                total = probe_duration(audio_path)
            except Exception:  # noqa: BLE001 - progress only
                total = 0.0
            process = self._popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        except OSError as error:
            raise AsrError(f"cannot run speech helper: {error}") from error
        segments: list[AsrSegment] = []
        duration = 0.0
        detected_locale = locale
        error_text: str | None = None
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("error"):
                error_text = str(payload["error"])
            elif "text" in payload:
                segment = AsrSegment(
                    start=float(payload.get("start", 0.0)),
                    end=float(payload.get("end", 0.0)),
                    text=str(payload["text"]).strip(),
                )
                if segment.text:
                    segments.append(segment)
                    if on_progress and total:
                        on_progress(min(segment.end, total), total)
            elif payload.get("done"):
                duration = float(payload.get("duration", 0.0))
                detected_locale = str(payload.get("locale", detected_locale))
        process.wait(timeout=60)
        stderr_tail = ""
        if process.stderr is not None:
            stderr_tail = process.stderr.read()[-400:]
        if error_text or process.returncode != 0:
            raise AsrError(error_text or f"speech helper failed: {stderr_tail}")
        if on_progress and total:
            on_progress(total, total)
        return AsrResult(
            language=detected_locale or "unknown",
            duration=duration or total,
            segments=segments,
        )
