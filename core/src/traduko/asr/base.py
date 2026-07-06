"""ASR provider abstraction: audio in, timed segments out."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class AsrError(Exception):
    pass


@dataclass
class AsrSegment:
    start: float
    end: float
    text: str


@dataclass
class AsrResult:
    language: str
    duration: float
    segments: list[AsrSegment]


@runtime_checkable
class AsrProvider(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float, float], None] | None = None,
    ) -> AsrResult: ...


_REGISTRY: dict[str, type] = {}


def register_asr(name: str):
    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def create_asr(name: str, **params) -> AsrProvider:
    if name not in _REGISTRY:
        raise AsrError(f"unknown asr provider: {name}")
    return _REGISTRY[name](**params)
