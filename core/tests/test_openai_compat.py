import base64
import json
from pathlib import Path

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


def test_images_become_content_parts_with_data_url(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG-fake-bytes")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    provider.chat(
        ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="system", content="sys"),
                ChatMessage(role="user", content="look", images=[str(image)]),
            ],
        )
    )
    messages = captured["payload"]["messages"]
    assert messages[0]["content"] == "sys"
    parts = messages[1]["content"]
    assert parts[0] == {"type": "text", "text": "look"}
    encoded = base64.b64encode(b"\x89PNG-fake-bytes").decode("ascii")
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{encoded}"},
    }


def test_unreadable_image_is_skipped_not_fatal(tmp_path: Path) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    response = provider.chat(
        ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user", content="look", images=[str(tmp_path / "gone.png")]
                ),
            ],
        )
    )
    assert response.content == "translated"
    assert captured["payload"]["messages"][0]["content"] == [
        {"type": "text", "text": "look"}
    ]


def test_client_error_fails_immediately() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": "bad key"})

    provider = make_provider(handler)
    with pytest.raises(LLMError):
        provider.chat(make_request())
    assert calls["n"] == 1


UNSUPPORTED_MAX_TOKENS = {
    "error": {
        "message": (
            "Unsupported parameter: 'max_tokens' is not supported with this "
            "model. Use 'max_completion_tokens' instead."
        ),
        "type": "invalid_request_error",
        "param": "max_tokens",
    }
}


def test_max_tokens_falls_back_to_max_completion_tokens_and_sticks() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        payloads.append(payload)
        if "max_tokens" in payload:
            return httpx.Response(400, json=UNSUPPORTED_MAX_TOKENS)
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, max_output_tokens=128000)
    assert provider.chat(make_request()).content == "translated"
    assert payloads[0]["max_tokens"] == 128000
    assert payloads[1]["max_completion_tokens"] == 128000
    assert "max_tokens" not in payloads[1]
    # The switch is remembered: the next call goes straight to the new name.
    provider.chat(make_request())
    assert len(payloads) == 3
    assert payloads[2]["max_completion_tokens"] == 128000


def test_configured_max_output_tokens_caps_and_fills() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, max_output_tokens=100)
    request = make_request()
    request.max_tokens = 500
    provider.chat(request)
    request.max_tokens = 50
    provider.chat(request)
    request.max_tokens = None
    provider.chat(request)
    assert [p.get("max_tokens") for p in payloads] == [100, 50, 100]


def test_unrelated_400_is_not_retried_with_new_param() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    provider = make_provider(handler, max_output_tokens=100)
    with pytest.raises(LLMError):
        provider.chat(make_request())
    assert calls["n"] == 1


def test_null_content_maps_to_empty_string() -> None:
    body = {
        "model": "test-model",
        "choices": [{"message": {"role": "assistant", "content": None}}],
        "usage": {},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    provider = make_provider(handler)
    assert provider.chat(make_request()).content == ""
