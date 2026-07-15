"""Scripted provider: canned responses in order, for tests and e2e runs."""
from __future__ import annotations

from .base import ChatRequest, ChatResponse, LLMError, Usage, register_llm


@register_llm("scripted")
class ScriptedLLMProvider:
    def __init__(self, responses: list[str], **_ignored) -> None:
        self._responses = list(responses)
        self._index = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        if self._index >= len(self._responses):
            raise LLMError("scripted provider ran out of responses")
        content = self._responses[self._index]
        self._index += 1
        prompt = request.messages[-1].content
        return ChatResponse(
            content=content,
            model=request.model,
            usage=Usage(
                prompt_tokens=max(1, len(prompt) // 4),
                completion_tokens=max(1, len(content) // 4),
            ),
        )
