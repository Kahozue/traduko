import json

import pytest

from traduko.llm import ChatMessage, ChatRequest, LLMError, create_llm

SEGMENTS_PROMPT = """Translate the following.
Return ONLY a JSON array like [{"id": 1, "text": "example"}].

SEGMENTS:
[{"id": 1, "text": "hello"}, {"id": 2, "text": "world"}]
"""


def make_request(content: str) -> ChatRequest:
    return ChatRequest(model="fake-model", messages=[ChatMessage(role="user", content=content)])


def test_create_llm_fake() -> None:
    provider = create_llm({"type": "fake"})
    assert provider.chat(make_request("hi")).model == "fake-model"


def test_create_llm_unknown_type_raises() -> None:
    with pytest.raises(LLMError):
        create_llm({"type": "nope"})


def test_fake_translates_segments_array_aligned_by_id() -> None:
    provider = create_llm({"type": "fake"})
    response = provider.chat(make_request(SEGMENTS_PROMPT))
    items = json.loads(response.content)
    assert items == [
        {"id": 1, "text": "[T] hello"},
        {"id": 2, "text": "[T] world"},
    ]


def test_fake_translates_blocks_marker_with_string_ids() -> None:
    provider = create_llm({"type": "fake"})
    prompt = 'Sample [{"id": 0, "text": "rule example"}] in rules.\n\nBLOCKS:\n[{"id": "b-00001", "text": "hello"}]\n'
    response = provider.chat(make_request(prompt))
    assert json.loads(response.content) == [{"id": "b-00001", "text": "[T] hello"}]


def test_fake_echoes_without_segments_marker() -> None:
    provider = create_llm({"type": "fake"})
    assert provider.chat(make_request("just a question")).content == "just a question"


def test_fake_reports_usage() -> None:
    provider = create_llm({"type": "fake"})
    usage = provider.chat(make_request(SEGMENTS_PROMPT)).usage
    assert usage.prompt_tokens > 0 and usage.completion_tokens > 0


def test_scripted_provider_returns_in_order_then_raises() -> None:
    provider = create_llm({"type": "scripted", "responses": ["one", "two"]})
    assert provider.chat(make_request("a")).content == "one"
    assert provider.chat(make_request("b")).content == "two"
    with pytest.raises(LLMError):
        provider.chat(make_request("c"))


def test_scripted_reports_usage() -> None:
    provider = create_llm({"type": "scripted", "responses": ["out"]})
    usage = provider.chat(make_request("prompt")).usage
    assert usage.prompt_tokens > 0 and usage.completion_tokens > 0


def test_fake_finishes_agent_protocol_conversations() -> None:
    provider = create_llm({"type": "fake"})
    request = ChatRequest(
        model="fake-model",
        messages=[
            ChatMessage(role="system", content="Goal...\nAGENT_TOOLS:\n[]"),
            ChatMessage(role="user", content="Begin round 1."),
        ],
    )
    action = json.loads(provider.chat(request).content)
    assert action["done"] is True


def test_fake_chat_stream_emits_deltas_matching_content() -> None:
    provider = create_llm({"type": "fake"})
    deltas: list[str] = []
    response = provider.chat_stream(make_request("just a question"), deltas.append)
    assert len(deltas) > 1
    assert "".join(deltas) == response.content == "just a question"


def test_stream_chat_helper_falls_back_for_plain_providers() -> None:
    from traduko.llm import stream_chat

    provider = create_llm({"type": "scripted", "responses": ["only"]})
    deltas: list[str] = []
    response = stream_chat(provider, make_request("x"), deltas.append)
    assert deltas == ["only"]
    assert response.content == "only"
