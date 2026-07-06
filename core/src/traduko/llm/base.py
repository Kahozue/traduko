"""LLM provider abstraction. Runtime calls must go through BudgetMeter."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class LLMError(Exception):
    pass


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatRequest:
    model: str
    messages: list[ChatMessage]
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ChatResponse:
    content: str
    model: str
    usage: Usage


@runtime_checkable
class LLMProvider(Protocol):
    def chat(self, request: ChatRequest) -> ChatResponse: ...


_REGISTRY: dict[str, type] = {}


def register_llm(type_name: str):
    def decorator(cls: type) -> type:
        _REGISTRY[type_name] = cls
        return cls

    return decorator


def create_llm(config: dict) -> LLMProvider:
    cfg = dict(config)
    type_name = cfg.pop("type", None)
    if type_name not in _REGISTRY:
        raise LLMError(f"unknown llm provider type: {type_name}")
    return _REGISTRY[type_name](**cfg)
