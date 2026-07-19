"""TTS engine catalog: the dubbing studio's engine menu is backed by a
fixed catalog. Placeholder engines describe future cloud TTS options and
must refuse to synthesize so the backend rejects them even if the UI's
disabled state is bypassed."""
from __future__ import annotations

import pytest

from traduko.dubbing.client import DubbingError
from traduko.dubbing.engines import (
    TTS_ENGINES,
    TtsEngineInfo,
    engine_for_id,
    resolve_tts_engine,
)


def test_catalog_lists_the_three_engines() -> None:
    ids = {engine.id for engine in TTS_ENGINES}
    assert ids == {"voxcpm2", "say_preview", "cloud_placeholder"}


def test_each_engine_carries_kind_and_voice_modes() -> None:
    by_id = {engine.id: engine for engine in TTS_ENGINES}
    assert by_id["voxcpm2"].kind == "local"
    assert by_id["voxcpm2"].voice_modes == ("clone", "design")
    assert by_id["say_preview"].kind == "local"
    assert by_id["say_preview"].voice_modes == ("preview",)
    assert by_id["cloud_placeholder"].kind == "placeholder"
    assert by_id["cloud_placeholder"].voice_modes == ()


def test_resolve_returns_real_engines() -> None:
    engine = resolve_tts_engine("voxcpm2")
    assert isinstance(engine, TtsEngineInfo)
    assert engine.id == "voxcpm2"


def test_resolve_rejects_placeholder() -> None:
    with pytest.raises(DubbingError, match="cloud_placeholder"):
        resolve_tts_engine("cloud_placeholder")


def test_resolve_rejects_unknown_id() -> None:
    with pytest.raises(DubbingError, match="unknown tts engine"):
        resolve_tts_engine("nope")


def test_engine_for_id_returns_none_for_unknown() -> None:
    assert engine_for_id("nope") is None
    assert engine_for_id("voxcpm2") is not None
