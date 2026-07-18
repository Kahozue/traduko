"""OpenAI-compatible chat provider (OpenAI, DeepSeek, Groq, Ollama, LM Studio)."""
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


def _message_content(message: ChatMessage) -> str | list[dict]:
    """Plain string normally; OpenAI content-parts when images are attached.

    Each readable image becomes an image_url part with a base64 data URL.
    An image that disappeared between attach and send is skipped rather than
    failing the chat: its path still reaches the model as text, so the model
    can report the missing file itself.
    """
    if not message.images:
        return message.content
    parts: list[dict] = [{"type": "text", "text": message.content}]
    for path in message.images:
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        mime = mimetypes.guess_type(path)[0]
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        parts.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
        )
    return parts


@register_llm("openai_compat")
class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
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
        # Newer OpenAI models reject max_tokens and demand max_completion_tokens;
        # most compatible endpoints (DeepSeek, GLM, Kimi, proxies) still speak
        # max_tokens. Start with the widely-supported name and switch for the
        # rest of this provider's lifetime the first time the endpoint says so.
        self._tokens_param = "max_tokens"
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def _effective_max_tokens(self, request: ChatRequest) -> int | None:
        if request.max_tokens is not None and self.max_output_tokens is not None:
            return min(request.max_tokens, self.max_output_tokens)
        if request.max_tokens is not None:
            return request.max_tokens
        return self.max_output_tokens

    def _build_payload(self, request: ChatRequest) -> dict:
        payload: dict = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": _message_content(m)}
                for m in request.messages
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        max_tokens = self._effective_max_tokens(request)
        if max_tokens is not None:
            payload[self._tokens_param] = max_tokens
        return payload

    def _headers(self) -> dict:
        headers: dict = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, request: ChatRequest) -> ChatResponse:
        payload = self._build_payload(request)
        headers = self._headers()

        try:
            data = self._post(payload, headers)
        except LLMError as error:
            # http 400 "Unsupported parameter: 'max_tokens' ... Use
            # 'max_completion_tokens' instead." — retry once under the new
            # name and keep using it for subsequent calls.
            if (
                self._tokens_param == "max_tokens"
                and "max_tokens" in payload
                and "max_completion_tokens" in str(error)
            ):
                self._tokens_param = "max_completion_tokens"
                payload["max_completion_tokens"] = payload.pop("max_tokens")
                data = self._post(payload, headers)
            else:
                raise
        usage = data.get("usage") or {}
        return ChatResponse(
            content=data["choices"][0]["message"]["content"] or "",
            model=data.get("model", request.model),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            ),
        )

    def _post(self, payload: dict, headers: dict) -> dict:
        return request_with_retries(
            self._client,
            f"{self.base_url}/chat/completions",
            payload,
            headers,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
        )

    def chat_stream(
        self, request: ChatRequest, on_delta: DeltaCallback
    ) -> ChatResponse:
        """SSE streaming with usage in the final chunk. Any streaming-path
        failure falls back to the plain call so budget metering stays exact;
        the consumer then sees one delta with the whole reply (a rare
        mid-stream failure may replay already-seen text, which downstream
        renderers overwrite with the final content anyway)."""
        payload = self._build_payload(request)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
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
            f"{self.base_url}/chat/completions",
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
                if data_str == "[DONE]":
                    break
                chunk = json.loads(data_str)
                model = chunk.get("model") or model
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        parts.append(delta)
                        on_delta(delta)
                if chunk.get("usage"):
                    raw = chunk["usage"]
                    usage = Usage(
                        prompt_tokens=raw.get("prompt_tokens", 0),
                        completion_tokens=raw.get("completion_tokens", 0),
                    )
        return ChatResponse(content="".join(parts), model=model, usage=usage)
