"""LLM provider abstraction. Runtime calls must go through BudgetMeter."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

DeltaCallback = Callable[[str], None]


class LLMError(Exception):
    pass


@dataclass
class ChatMessage:
    role: str
    content: str
    # Absolute paths to local image files attached to this message. Providers
    # that support vision send the pixels alongside the text; the rest ignore
    # this field, so text-only behavior is unchanged when it is empty.
    images: list[str] = field(default_factory=list)


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


def stream_chat(
    provider: LLMProvider, request: ChatRequest, on_delta: DeltaCallback
) -> ChatResponse:
    """Stream when the provider can, degrade to one delta when it cannot.

    Callers always observe the full reply through on_delta either way, so
    UI code needs no capability checks."""
    stream = getattr(provider, "chat_stream", None)
    if callable(stream):
        return stream(request, on_delta)
    response = provider.chat(request)
    if response.content:
        on_delta(response.content)
    return response


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
