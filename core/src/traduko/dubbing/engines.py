"""TTS engine catalog for the dubbing studio.

The studio's engine menu is backed by a fixed catalog of ``TtsEngineInfo``
entries. Real engines (VoxCPM2, the macOS ``say`` preview) map onto the
existing voice_mode dispatch in ``stages/dub.py``; the placeholder entry
describes a future cloud TTS option and must refuse to synthesize so the
backend rejects it even if the UI's disabled state is bypassed.

This module is intentionally a thin descriptor layer: it does not own
synthesis. The stage runner still dispatches by ``voice_mode``; engine_id
is the user-facing handle the studio writes into stage params, and
``resolve_tts_engine`` is the guard the runner consults to reject
placeholder ids before any heavy work starts.
"""
from __future__ import annotations

from dataclasses import dataclass

from .client import DubbingError


@dataclass(frozen=True)
class TtsEngineInfo:
    id: str
    kind: str  # local | cloud | placeholder
    # Voice modes this engine can serve. voxcpm2 covers clone + design; the
    # say preview engine only serves the preview mode; placeholders serve none.
    voice_modes: tuple[str, ...]
    available: bool = True


TTS_ENGINES: tuple[TtsEngineInfo, ...] = (
    TtsEngineInfo("voxcpm2", "local", ("clone", "design")),
    TtsEngineInfo("say_preview", "local", ("preview",)),
    TtsEngineInfo("cloud_placeholder", "placeholder", (), available=False),
)

_BY_ID: dict[str, TtsEngineInfo] = {engine.id: engine for engine in TTS_ENGINES}


def engine_for_id(engine_id: str) -> TtsEngineInfo | None:
    """Return the catalog entry for ``engine_id`` or None if unknown."""
    return _BY_ID.get(engine_id)


def resolve_tts_engine(engine_id: str) -> TtsEngineInfo:
    """Resolve an engine id to a runnable engine.

    Raises ``DubbingError`` for unknown ids and for placeholder engines,
    so the executor never hands a placeholder to the synthesis path even
    if the studio's disabled UI state is bypassed.
    """
    engine = _BY_ID.get(engine_id)
    if engine is None:
        raise DubbingError(f"unknown tts engine: {engine_id}")
    if engine.kind == "placeholder" or not engine.available:
        raise DubbingError(f"engine not available: {engine_id}")
    return engine
