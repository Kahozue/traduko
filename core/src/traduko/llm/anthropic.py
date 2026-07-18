"""Anthropic Messages API provider (native protocol, not OpenAI-compatible).

Speaks POST /messages with x-api-key + anthropic-version headers. System
messages move to the top-level `system` field; images ride along as base64
`image` content parts for vision-capable models.
"""
from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

import httpx

from ._http import request_with_retries
from .base import ChatMessage, ChatRequest, ChatResponse, Usage, register_llm

_DEFAULT_MAX_TOKENS = 4096


def _content_blocks(message: ChatMessage) -> str | list[dict]:
    """Plain string normally; Anthropic content blocks when images attach.

    An image that vanished between attach and send is skipped rather than
    failing the call: its path still reaches the model as text.
    """
    if not message.images:
        return message.content
    blocks: list[dict] = [{"type": "text", "text": message.content}]
    for path in message.images:
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        mime = mimetypes.guess_type(path)[0]
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            }
        )
    return blocks


@register_llm("anthropic")
class AnthropicProvider:
    def __init__(
        self,
        base_url: str = "https://api.anthropic.com/v1",
        api_key: str | None = None,
        api_key_env: str | None = None,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
        anthropic_version: str = "2023-06-01",
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if api_key is None and api_key_env:
            api_key = os.environ.get(api_key_env)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        self.anthropic_version = anthropic_version
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def chat(self, request: ChatRequest) -> ChatResponse:
        system_parts = [
            m.content for m in request.messages if m.role == "system" and m.content
        ]
        # The Messages API requires max_tokens: an explicit request wins
        # (clamped to the configured model ceiling), then the configured
        # ceiling, then a conservative default.
        max_tokens = request.max_tokens or self.max_output_tokens or _DEFAULT_MAX_TOKENS
        if self.max_output_tokens is not None:
            max_tokens = min(max_tokens, self.max_output_tokens)
        payload: dict = {
            "model": request.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": m.role, "content": _content_blocks(m)}
                for m in request.messages
                if m.role != "system"
            ],
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        headers = {"anthropic-version": self.anthropic_version}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        data = request_with_retries(
            self._client,
            f"{self.base_url}/messages",
            payload,
            headers,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
        )
        content = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage = data.get("usage") or {}
        return ChatResponse(
            content=content,
            model=data.get("model", request.model),
            usage=Usage(
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
            ),
        )
