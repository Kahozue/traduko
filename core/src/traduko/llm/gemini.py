"""Google Gemini generateContent provider (native protocol).

Speaks POST /models/{model}:generateContent with an x-goog-api-key header.
System messages move to `systemInstruction`; assistant turns map to the
`model` role; images ride along as base64 inline_data parts.
"""
from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

import httpx

from ._http import request_with_retries
from .base import ChatMessage, ChatRequest, ChatResponse, LLMError, Usage, register_llm


def _parts(message: ChatMessage) -> list[dict]:
    """Text part plus one inline_data part per readable image.

    An image that vanished between attach and send is skipped rather than
    failing the call.
    """
    parts: list[dict] = [{"text": message.content}]
    for path in message.images:
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        mime = mimetypes.guess_type(path)[0]
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(data).decode("ascii"),
                }
            }
        )
    return parts


@register_llm("gemini")
class GeminiProvider:
    def __init__(
        self,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        api_key: str | None = None,
        api_key_env: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if api_key is None and api_key_env:
            api_key = os.environ.get(api_key_env)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def chat(self, request: ChatRequest) -> ChatResponse:
        system_parts = [
            m.content for m in request.messages if m.role == "system" and m.content
        ]
        contents = [
            {
                "role": "model" if m.role == "assistant" else "user",
                "parts": _parts(m),
            }
            for m in request.messages
            if m.role != "system"
        ]
        payload: dict = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n".join(system_parts)}]
            }
        generation: dict = {}
        if request.temperature is not None:
            generation["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation["maxOutputTokens"] = request.max_tokens
        if generation:
            payload["generationConfig"] = generation

        headers = {}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key

        data = request_with_retries(
            self._client,
            f"{self.base_url}/models/{request.model}:generateContent",
            payload,
            headers,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
        )
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMError("gemini returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        content = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata") or {}
        return ChatResponse(
            content=content,
            model=data.get("modelVersion", request.model),
            usage=Usage(
                prompt_tokens=usage.get("promptTokenCount", 0),
                completion_tokens=usage.get("candidatesTokenCount", 0),
            ),
        )
