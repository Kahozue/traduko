"""Deterministic offline provider for tests and dry runs."""
from __future__ import annotations

import json
import re

from .base import ChatRequest, ChatResponse, Usage, register_llm

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


@register_llm("fake")
class FakeLLMProvider:
    def __init__(self, prefix: str = "[T] ", **_ignored) -> None:
        self.prefix = prefix

    def chat(self, request: ChatRequest) -> ChatResponse:
        full_prompt = "\n".join(m.content for m in request.messages)
        prompt = request.messages[-1].content
        if "AGENT_TOOLS:" in full_prompt:
            content = json.dumps(
                {"done": True, "summary": "fake provider: no issues found"}
            )
            return ChatResponse(
                content=content,
                model=request.model,
                usage=Usage(
                    prompt_tokens=max(1, len(full_prompt) // 4),
                    completion_tokens=max(1, len(content) // 4),
                ),
            )
        content = prompt
        if "SEGMENTS:" in prompt:
            tail = prompt.rsplit("SEGMENTS:", 1)[-1]
            match = _ARRAY_RE.search(tail)
            if match:
                try:
                    items = json.loads(match.group(0))
                except json.JSONDecodeError:
                    items = None
                if isinstance(items, list):
                    out = [
                        {"id": item["id"], "text": self.prefix + str(item.get("text", ""))}
                        for item in items
                    ]
                    content = json.dumps(out, ensure_ascii=False)
        return ChatResponse(
            content=content,
            model=request.model,
            usage=Usage(
                prompt_tokens=max(1, len(prompt) // 4),
                completion_tokens=max(1, len(content) // 4),
            ),
        )
