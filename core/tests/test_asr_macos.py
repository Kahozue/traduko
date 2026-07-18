"""MacosAsrManager and provider tests with injected runner/compiler."""
import json
import subprocess
from pathlib import Path

import pytest

from traduko.asr import AsrError, create_asr
from traduko.asr.macos import MacosAsrManager, helper_binary


def completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def fake_compiler(source: Path, output: Path) -> None:
    output.write_text("#!/bin/sh\n", encoding="utf-8")


PROBE_LINE = json.dumps(
    {
        "available": True,
        "os_ok": True,
        "transcriber_locales": ["zh-TW", "ja-JP"],
        "dictation_locales": ["zh-TW", "ja-JP", "th-TH"],
        "installed": ["zh-TW"],
    }
)


def test_status_reports_probe_and_compiles_once(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return completed(PROBE_LINE + "\n")

    manager = MacosAsrManager(
        tmp_path, runner=runner, compiler=fake_compiler, platform_system="Darwin"
    )
    status = manager.status()
    assert status["available"] is True
    assert status["transcriber_locales"] == ["zh-TW", "ja-JP"]
    assert status["installed_locales"] == ["zh-TW"]
    assert helper_binary(tmp_path).exists()
    # Cached probe: a second status call within the cache window runs nothing.
    manager.status()
    assert len(calls) == 1


def test_status_on_non_darwin_is_unavailable(tmp_path: Path) -> None:
    manager = MacosAsrManager(
        tmp_path, runner=lambda cmd, **k: completed(), platform_system="Linux"
    )
    status = manager.status()
    assert status["platform_ok"] is False
    assert status["available"] is False


def test_assets_download_tracks_progress_and_errors(tmp_path: Path) -> None:
    def runner(cmd, **kwargs):
        if "assets" in cmd:
            lines = "\n".join(
                [json.dumps({"progress": 0.5}), json.dumps({"done": True})]
            )
            return completed(lines + "\n")
        return completed(PROBE_LINE + "\n")

    manager = MacosAsrManager(
        tmp_path, runner=runner, compiler=fake_compiler, platform_system="Darwin"
    )
    assert manager.start_assets("zh-TW") is True
    # The worker thread is fast with the fake runner; poll briefly.
    import time

    for _ in range(50):
        state = manager.status()["assets_state"]
        if state in ("done", "error"):
            break
        time.sleep(0.01)
    assert manager.status()["assets_state"] == "done"
    assert manager.status()["assets_progress"] == 1.0


def test_provider_parses_helper_segments(tmp_path: Path) -> None:
    binary = helper_binary(tmp_path)
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\n")

    class FakeProcess:
        def __init__(self):
            self.stdout = iter(
                [
                    json.dumps({"start": 0.0, "end": 2.5, "text": "你好"}) + "\n",
                    json.dumps({"done": True, "duration": 2.5, "locale": "zh-TW"})
                    + "\n",
                ]
            )
            self.stderr = None
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

    provider = create_asr(
        "macos_native",
        locale="zh-TW",
        data_root=str(tmp_path),
        runner=lambda cmd, **kwargs: FakeProcess(),
    )
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"riff")
    result = provider.transcribe(audio)
    assert result.language == "zh-TW"
    assert result.duration == 2.5
    assert [s.text for s in result.segments] == ["你好"]
    assert result.timestamps is True


def test_provider_surfaces_helper_error(tmp_path: Path) -> None:
    binary = helper_binary(tmp_path)
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text("#!/bin/sh\n")

    class FailingProcess:
        def __init__(self):
            self.stdout = iter([json.dumps({"error": "locale not supported: xx"}) + "\n"])
            self.stderr = None
            self.returncode = 1

        def wait(self, timeout=None):
            return 1

    provider = create_asr(
        "macos_native",
        locale="xx",
        data_root=str(tmp_path),
        runner=lambda cmd, **kwargs: FailingProcess(),
    )
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"riff")
    with pytest.raises(AsrError, match="locale not supported"):
        provider.transcribe(audio)


def test_provider_without_compiled_helper_raises(tmp_path: Path) -> None:
    provider = create_asr("macos_native", locale="zh-TW", data_root=str(tmp_path))
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"riff")
    with pytest.raises(AsrError, match="not compiled"):
        provider.transcribe(audio)
