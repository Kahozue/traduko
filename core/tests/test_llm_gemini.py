import base64
import json
from pathlib import Path

import httpx
import pytest

from traduko.llm import ChatMessage, ChatRequest, LLMError, create_llm

OK_BODY = {
    "modelVersion": "gemini-test",
    "candidates": [{"content": {"parts": [{"text": "translated"}]}}],
    "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4},
}


def make_provider(handler, **kwargs):
    return create_llm(
        {
            "type": "gemini",
            "base_url": "https://gemini.test/v1beta",
            "transport": httpx.MockTransport(handler),
            "backoff_base": 0.0,
            **kwargs,
        }
    )


def make_request(messages=None, **kwargs) -> ChatRequest:
    return ChatRequest(
        model="gemini-test",
        messages=messages or [ChatMessage(role="user", content="hi")],
        **kwargs,
    )


def test_success_maps_content_and_usage() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content)
        captured["key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, api_key="g-key")
    response = provider.chat(make_request(temperature=0.5, max_tokens=256))
    assert response.content == "translated"
    assert response.usage.prompt_tokens == 9
    assert response.usage.completion_tokens == 4
    assert captured["url"].endswith("/models/gemini-test:generateContent")
    assert captured["key"] == "g-key"
    assert captured["payload"]["generationConfig"]["temperature"] == 0.5
    assert captured["payload"]["generationConfig"]["maxOutputTokens"] == 256


def test_system_and_role_mapping() -> None:
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
                ChatMessage(role="assistant", content="prev"),
            ]
        )
    )
    payload = captured["payload"]
    assert payload["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert [c["role"] for c in payload["contents"]] == ["user", "model"]


def test_image_becomes_inline_data(tmp_path: Path) -> None:
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
    parts = captured["payload"]["contents"][0]["parts"]
    assert parts[0] == {"text": "what"}
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert base64.b64decode(parts[1]["inline_data"]["data"]) == b"\x89PNGfake"


def test_empty_candidates_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    provider = make_provider(handler)
    with pytest.raises(LLMError):
        provider.chat(make_request())


def test_retries_on_transient_status() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="err")
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler)
    assert provider.chat(make_request()).content == "translated"
    assert calls["n"] == 2


def test_configured_max_output_tokens_fills_and_caps() -> None:
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    provider = make_provider(handler, max_output_tokens=65536)
    provider.chat(make_request())
    provider.chat(make_request(max_tokens=128))
    provider.chat(make_request(max_tokens=999999))
    assert [
        p["generationConfig"]["maxOutputTokens"] for p in payloads
    ] == [65536, 128, 65536]


def test_chat_stream_parses_sse_and_usage() -> None:
    chunks = [
        {"candidates": [{"content": {"parts": [{"text": "Bon"}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "jour"}]}}],
         "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 2}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert ":streamGenerateContent" in str(request.url)
        assert "alt=sse" in str(request.url)
        return httpx.Response(200, content=body)

    provider = make_provider(handler)
    deltas: list[str] = []
    response = provider.chat_stream(make_request(), deltas.append)
    assert deltas == ["Bon", "jour"]
    assert response.content == "Bonjour"
    assert response.usage.prompt_tokens == 9
    assert response.usage.completion_tokens == 2
