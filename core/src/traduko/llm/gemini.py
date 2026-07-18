"""Google Gemini generateContent provider (native protocol).

Speaks POST /models/{model}:generateContent with an x-goog-api-key header.
System messages move to `systemInstruction`; assistant turns map to the
`model` role; images ride along as base64 inline_data parts.
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
        context_window: int | None = None,
        max_output_tokens: int | None = None,
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
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = self._build_payload(request)
        headers = self._headers()

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

    def _build_payload(self, request: ChatRequest) -> dict:
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
        max_tokens = request.max_tokens or self.max_output_tokens
        if max_tokens is not None:
            if self.max_output_tokens is not None:
                max_tokens = min(max_tokens, self.max_output_tokens)
            generation["maxOutputTokens"] = max_tokens
        if generation:
            payload["generationConfig"] = generation
        return payload

    def _headers(self) -> dict:
        headers: dict = {}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key
        return headers

    def chat_stream(
        self, request: ChatRequest, on_delta: DeltaCallback
    ) -> ChatResponse:
        """streamGenerateContent?alt=sse; the last chunk carries usage.
        Failures fall back to the plain call so budget metering stays exact."""
        payload = self._build_payload(request)
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
            f"{self.base_url}/models/{request.model}:streamGenerateContent?alt=sse",
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
                chunk = json.loads(data_str)
                model = chunk.get("modelVersion") or model
                candidates = chunk.get("candidates") or []
                if candidates:
                    for part in candidates[0].get("content", {}).get("parts", []):
                        text = part.get("text", "")
                        if text:
                            parts.append(text)
                            on_delta(text)
                meta = chunk.get("usageMetadata")
                if meta:
                    usage = Usage(
                        prompt_tokens=meta.get("promptTokenCount", 0),
                        completion_tokens=meta.get("candidatesTokenCount", 0),
                    )
        return ChatResponse(content="".join(parts), model=model, usage=usage)
