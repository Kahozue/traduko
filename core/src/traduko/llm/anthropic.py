"""Anthropic Messages API provider (native protocol, not OpenAI-compatible).

Speaks POST /messages with x-api-key + anthropic-version headers. System
messages move to the top-level `system` field; images ride along as base64
`image` content parts for vision-capable models.
"""
from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path

import httpx

from ._http import request_with_retries
from .base import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DeltaCallback,
    LLMError,
    Usage,
    register_llm,
)

logger = logging.getLogger(__name__)

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
        payload = self._build_payload(request)
        headers = self._headers()

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

    def _build_payload(self, request: ChatRequest) -> dict:
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
        return payload

    def _headers(self) -> dict:
        headers = {"anthropic-version": self.anthropic_version}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def chat_stream(
        self, request: ChatRequest, on_delta: DeltaCallback
    ) -> ChatResponse:
        """SSE streaming (message_start carries input usage, message_delta
        the output usage). Failures fall back to the plain call so budget
        metering stays exact."""
        payload = self._build_payload(request)
        payload["stream"] = True
        try:
            return self._stream(payload, request, on_delta)
        except (LLMError, httpx.HTTPError, json.JSONDecodeError) as error:
            logger.debug("stream failed, falling back to plain chat: %s", error)
            response = self.chat(request)
            if response.content:
                on_delta(response.content)
            return response

    def _stream(
        self, payload: dict, request: ChatRequest, on_delta: DeltaCallback
    ) -> ChatResponse:
        parts: list[str] = []
        usage = Usage()
        model = request.model
        with self._client.stream(
            "POST",
            f"{self.base_url}/messages",
            json=payload,
            headers=self._headers(),
        ) as response:
            if response.status_code != 200:
                body = response.read().decode("utf-8", errors="replace")[:200]
                raise LLMError(
                    f"llm call failed: http {response.status_code}: {body}"
                )
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[len("data:") :].strip()
                if not data_str:
                    continue
                event = json.loads(data_str)
                kind = event.get("type")
                if kind == "message_start":
                    message = event.get("message") or {}
                    model = message.get("model") or model
                    usage.prompt_tokens = (message.get("usage") or {}).get(
                        "input_tokens", 0
                    )
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        parts.append(delta["text"])
                        on_delta(delta["text"])
                elif kind == "message_delta":
                    output = (event.get("usage") or {}).get("output_tokens")
                    if output is not None:
                        usage.completion_tokens = output
                elif kind == "message_stop":
                    break
        return ChatResponse(content="".join(parts), model=model, usage=usage)
