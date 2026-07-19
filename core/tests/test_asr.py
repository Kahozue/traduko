import sys
import types
from pathlib import Path

import pytest

from traduko.asr import AsrError, AsrResult, create_asr


def test_unknown_provider_raises() -> None:
    with pytest.raises(AsrError):
        create_asr("nope")


def make_fake_faster_whisper(recorder: dict):
    module = types.ModuleType("faster_whisper")

    class WhisperModel:
        def __init__(self, model_size, device="auto", compute_type="auto"):
            recorder["init"] = (model_size, device, compute_type)

        def transcribe(
            self, path, language=None, vad_filter=True, initial_prompt=None
        ):
            recorder["transcribe"] = {
                "path": path,
                "language": language,
                "vad_filter": vad_filter,
                "initial_prompt": initial_prompt,
            }
            segments = [
                types.SimpleNamespace(start=0.0, end=1.5, text=" Hello there. "),
                types.SimpleNamespace(start=1.6, end=2.0, text="   "),
                types.SimpleNamespace(start=2.0, end=3.0, text="Bye."),
            ]
            info = types.SimpleNamespace(language="en", duration=3.0)
            return iter(segments), info

    module.WhisperModel = WhisperModel
    return module


def test_whisper_maps_segments_and_reports_progress(monkeypatch, tmp_path: Path) -> None:
    recorder: dict = {}
    monkeypatch.setitem(sys.modules, "faster_whisper", make_fake_faster_whisper(recorder))
    provider = create_asr("faster_whisper", model_size="tiny")
    progress: list[tuple[float, float]] = []
    result = provider.transcribe(
        tmp_path / "01-audio.wav", language=None, on_progress=lambda a, b: progress.append((a, b))
    )
    assert isinstance(result, AsrResult)
    assert recorder["init"] == ("tiny", "auto", "auto")
    assert recorder["transcribe"]["language"] is None
    assert result.language == "en" and result.duration == 3.0
    assert [s.text for s in result.segments] == ["Hello there.", "Bye."]
    assert progress[-1] == (3.0, 3.0)


def test_whisper_passes_glossary_terms_as_initial_prompt(
    monkeypatch, tmp_path: Path
) -> None:
    recorder: dict = {}
    monkeypatch.setitem(sys.modules, "faster_whisper", make_fake_faster_whisper(recorder))
    provider = create_asr("faster_whisper", model_size="tiny")

    provider.transcribe(
        tmp_path / "01-audio.wav", glossary_terms=["Traduko", "桐人"]
    )

    assert recorder["transcribe"]["initial_prompt"] == "Traduko 桐人"


def test_whisper_missing_dependency_raises_asr_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    provider = create_asr("faster_whisper")
    with pytest.raises(AsrError, match="faster-whisper"):
        provider.transcribe(tmp_path / "01-audio.wav")
