from __future__ import annotations

from .base import Stage, UnknownStageError

_REGISTRY: dict[str, type] = {}


def register(cls: type) -> type:
    _REGISTRY[cls.type] = cls
    return cls


def create(type_name: str) -> Stage:
    if type_name not in _REGISTRY:
        raise UnknownStageError(f"unknown stage type: {type_name}")
    return _REGISTRY[type_name]()
