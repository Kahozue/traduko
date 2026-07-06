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


def test_fake_echoes_without_segments_marker() -> None:
    provider = create_llm({"type": "fake"})
    assert provider.chat(make_request("just a question")).content == "just a question"


def test_fake_reports_usage() -> None:
    provider = create_llm({"type": "fake"})
    usage = provider.chat(make_request(SEGMENTS_PROMPT)).usage
    assert usage.prompt_tokens > 0 and usage.completion_tokens > 0
