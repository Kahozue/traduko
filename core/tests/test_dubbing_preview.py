"""The say-based preview engine: voice listing, language matching,
deterministic rate fitting, and the synthesis subprocess contract."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from traduko.dubbing.client import DubbingError
from traduko.dubbing import preview
from traduko.dubbing.preview import (
    PREVIEW_BASE_RATE,
    PREVIEW_MAX_RATE,
    SayVoice,
    fit_rate,
    list_voices,
    pick_voice,
    synthesize_preview,
)

SAY_LISTING = """\
Alex                en_US    # Most people recognize me by my voice.
Bad News            en_US    # The light you see at the end of the tunnel.
Mei-Jia             zh_TW    # 您好，我叫美佳。
Sin-ji              zh_HK    # 嗨。
Kyoko               ja_JP    # こんにちは
not a voice line
"""


def fake_runner(returncode=0, stdout="", stderr=""):
    calls = []

    def run(cmd, *, input_text=None):
        calls.append((cmd, input_text))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    run.calls = calls
    return run


def test_list_voices_parses_names_with_spaces() -> None:
    voices = list_voices(runner=fake_runner(stdout=SAY_LISTING))
    assert SayVoice(name="Bad News", locale="en_US") in voices
    assert SayVoice(name="Mei-Jia", locale="zh_TW") in voices
    assert len(voices) == 5


def test_list_voices_failure_raises() -> None:
    with pytest.raises(DubbingError):
        list_voices(runner=fake_runner(returncode=1, stderr="nope"))


def test_pick_voice_prefers_exact_locale_then_primary_subtag() -> None:
    voices = list_voices(runner=fake_runner(stdout=SAY_LISTING))
    assert pick_voice(voices, "zh-TW") == "Mei-Jia"
    assert pick_voice(voices, "zh_HK") == "Sin-ji"
    assert pick_voice(voices, "zh") == "Mei-Jia"
    assert pick_voice(voices, "ja") == "Kyoko"
    assert pick_voice(voices, "fr") is None
    assert pick_voice(voices, None) is None
    assert pick_voice(voices, "") is None


def test_pick_voice_prefers_classic_over_novelty() -> None:
    voices = [
        SayVoice(name="Eddy (中文（台灣）)", locale="zh_TW"),
        SayVoice(name="Meijia", locale="zh_TW"),
    ]
    assert pick_voice(voices, "zh-TW") == "Meijia"
    # Only novelty voices installed: still usable rather than None.
    only_novelty = [SayVoice(name="Grandpa (中文（台灣）)", locale="zh_TW")]
    assert pick_voice(only_novelty, "zh-TW") == "Grandpa (中文（台灣）)"


def test_fit_rate_scales_capped_and_floored() -> None:
    assert fit_rate(0, 5.0) == PREVIEW_BASE_RATE
    assert fit_rate(5.0, 0) == PREVIEW_BASE_RATE
    # Already fits: never slower than base.
    assert fit_rate(5.0, 3.0) == PREVIEW_BASE_RATE
    # 180 * 4 * 1.02 / 3 = 244.8 -> 245.
    assert fit_rate(3.0, 4.0) == 245
    # Far too long: capped for intelligibility.
    assert fit_rate(1.0, 10.0) == PREVIEW_MAX_RATE


def test_synthesize_preview_builds_cmd_and_feeds_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "seg-1.aiff"
    calls = []

    def run(cmd, *, input_text=None):
        calls.append((cmd, input_text))
        out.write_bytes(b"aiff")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(preview, "probe_duration", lambda path: 2.5)
    duration = synthesize_preview(
        "你好世界", out, voice="Mei-Jia", rate=210, runner=run
    )
    assert duration == 2.5
    cmd, fed = calls[0]
    assert cmd == ["say", "-o", str(out), "-v", "Mei-Jia", "-r", "210"]
    assert fed == "你好世界"


def test_synthesize_preview_omits_voice_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "seg-2.aiff"

    def run(cmd, *, input_text=None):
        out.write_bytes(b"aiff")
        assert "-v" not in cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(preview, "probe_duration", lambda path: 1.0)
    assert synthesize_preview("hi", out, runner=run) == 1.0


def test_synthesize_preview_error_paths(tmp_path: Path) -> None:
    out = tmp_path / "seg-3.aiff"
    with pytest.raises(DubbingError, match="say synthesis failed"):
        synthesize_preview("hi", out, runner=fake_runner(returncode=1, stderr="bad"))
    # Zero exit but no file on disk is still a failure.
    with pytest.raises(DubbingError, match="no output"):
        synthesize_preview("hi", out, runner=fake_runner(returncode=0))
