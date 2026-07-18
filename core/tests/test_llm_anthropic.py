import base64
import json
from pathlib import Path

import httpx
import pytest

from traduko.llm import ChatMessage, ChatRequest, LLMError, create_llm

OK_BODY = {
    "model": "claude-test",
    "content": [{"type": "text", "text": "translated"}],
    "usage": {"input_tokens": 12, "output_tokens": 7},
}


def make_provider(handler, **kwargs):
    return create_llm(
        {
            "type": "anthropic",
            "base_url": "https://api.anthropic.test/v1",
            "transport": httpx.MockTransport(handler),
            "backoff_base": 0.0,
            **kwargs,
        }
    )


def make_request(messages=None, **kwargs) -> ChatRequest:
    return ChatRequest(
        model="claude-test",
        messages=messages or [ChatMessage(role="user", content="hi")],
        **kwargs,
    )


def test_success_maps_content_and_usage() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        captured["key"] = request.headers.get("x-api-key")
        captured["version"] = request.headers.get("anthropic-version")
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, api_key="sk-ant")
    response = provider.chat(make_request(temperature=0.3))
    assert response.content == "translated"
    assert response.usage.prompt_tokens == 12
    assert response.usage.completion_tokens == 7
    assert captured["url"].endswith("/v1/messages")
    assert captured["key"] == "sk-ant"
    assert captured["version"] == "2023-06-01"
    assert captured["payload"]["max_tokens"] == 4096
    assert captured["payload"]["temperature"] == 0.3


def test_system_message_moves_to_top_level() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    provider.chat(
        make_request(
            messages=[
                ChatMessage(role="system", content="be terse"),
                ChatMessage(role="user", content="hi"),
            ]
        )
    )
    assert captured["payload"]["system"] == "be terse"
    assert [m["role"] for m in captured["payload"]["messages"]] == ["user"]


def test_image_becomes_base64_block(tmp_path: Path) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNGfake")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    provider.chat(
        make_request(
            messages=[ChatMessage(role="user", content="what", images=[str(image)])]
        )
    )
    blocks = captured["payload"]["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "what"}
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"]["media_type"] == "image/png"
    assert base64.b64decode(blocks[1]["source"]["data"]) == b"\x89PNGfake"


def test_missing_image_is_skipped(tmp_path: Path) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    provider.chat(
        make_request(
            messages=[
                ChatMessage(role="user", content="hi", images=[str(tmp_path / "gone.png")])
            ]
        )
    )
    blocks = captured["payload"]["messages"][0]["content"]
    assert len(blocks) == 1


def test_retries_on_transient_status() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    response = provider.chat(make_request())
    assert response.content == "translated"
    assert calls["n"] == 2


def test_non_retryable_status_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad")

    provider = make_provider(handler)
    with pytest.raises(LLMError):
        provider.chat(make_request())


def test_configured_max_output_tokens_fills_and_caps() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, max_output_tokens=64000)
    provider.chat(make_request())
    provider.chat(make_request(max_tokens=100))
    provider.chat(make_request(max_tokens=999999))
    assert [p["max_tokens"] for p in payloads] == [64000, 100, 64000]


def test_chat_stream_parses_sse_and_usage() -> None:
    events = [
        ("message_start", {"type": "message_start", "message": {"model": "claude-x", "usage": {"input_tokens": 11}}}),
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi "}}),
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "there"}}),
        ("message_delta", {"type": "message_delta", "usage": {"output_tokens": 4}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        return httpx.Response(200, content=body)

    provider = make_provider(handler)
    deltas: list[str] = []
    response = provider.chat_stream(make_request(), deltas.append)
    assert deltas == ["Hi ", "there"]
    assert response.content == "Hi there"
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 4
