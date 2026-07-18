"""Shared retry skeleton for HTTP-based LLM providers.

All native adapters (OpenAI-compatible, Anthropic, Gemini) POST JSON and
retry the same transient statuses with the same exponential backoff, so
the loop lives here once. Response parsing stays in each adapter.
"""
from __future__ import annotations

import time

import httpx

from .base import LLMError

_RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retries(
    client: httpx.Client,
    url: str,
    payload: dict,
    headers: dict,
    *,
    max_retries: int,
    backoff_base: float,
) -> dict:
    """POST payload to url, retrying transient failures. Returns parsed JSON.

    Raises LLMError on a non-retryable status or once retries are exhausted.
    """
    last_error = ""
    for attempt in range(max_retries + 1):
        if attempt:
            time.sleep(backoff_base * (2 ** (attempt - 1)))
        try:
            response = client.post(url, json=payload, headers=headers)
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
        return response.json()
    raise LLMError(f"llm call failed after {max_retries + 1} attempts: {last_error}")
