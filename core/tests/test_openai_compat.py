import json

import httpx
import pytest

from traduko.llm import ChatMessage, ChatRequest, LLMError, create_llm

OK_BODY = {
    "model": "test-model",
    "choices": [{"message": {"role": "assistant", "content": "translated"}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def make_request() -> ChatRequest:
    return ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hi")],
        temperature=0.2,
    )


def make_provider(handler, **kwargs):
    return create_llm(
        {
            "type": "openai_compat",
            "base_url": "https://api.example.test/v1",
            "transport": httpx.MockTransport(handler),
            "backoff_base": 0.0,
            **kwargs,
        }
    )


def test_success_maps_content_and_usage() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, api_key="sk-test")
    response = provider.chat(make_request())
    assert response.content == "translated"
    assert response.usage.prompt_tokens == 10
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["payload"]["temperature"] == 0.2
    assert captured["auth"] == "Bearer sk-test"


def test_api_key_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "sk-env")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, api_key_env="TEST_LLM_KEY")
    provider.chat(make_request())
    assert captured["auth"] == "Bearer sk-env"


def test_retries_on_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    assert provider.chat(make_request()).content == "translated"
    assert calls["n"] == 2


def test_raises_after_exhausted_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    provider = make_provider(handler, max_retries=2)
    with pytest.raises(LLMError):
        provider.chat(make_request())


def test_client_error_fails_immediately() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    provider = make_provider(handler)
    with pytest.raises(LLMError):
        provider.chat(make_request())
    assert calls["n"] == 1
