"""OpenAI-compatible chat provider (OpenAI, DeepSeek, Groq, Ollama, LM Studio)."""
from __future__ import annotations

import os
import time

import httpx

from .base import ChatRequest, ChatResponse, LLMError, Usage, register_llm

_RETRY_STATUS = {429, 500, 502, 503, 504}


@register_llm("openai_compat")
class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
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
        payload: dict = {
            "model": request.model,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error = ""
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
            try:
                response = self._client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
            except httpx.TransportError as error:
                last_error = str(error)
                continue
            if response.status_code in _RETRY_STATUS:
                last_error = f"http {response.status_code}"
                continue
            if response.status_code != 200:
                raise LLMError(
                    f"llm call failed: http {response.status_code}: {response.text[:200]}"
                )
            data = response.json()
            usage = data.get("usage") or {}
            return ChatResponse(
                content=data["choices"][0]["message"]["content"],
                model=data.get("model", request.model),
                usage=Usage(
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                ),
            )
        raise LLMError(
            f"llm call failed after {self.max_retries + 1} attempts: {last_error}"
        )
