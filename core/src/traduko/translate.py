"""Batch translation engine with partial-progress resume.

Partial results land next to the final artifact as a JSON array so an
interrupted (crashed, paused, budget-capped) run continues where it left
off instead of re-spending tokens.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .budget import BudgetMeter
from .fsutil import atomic_write_text
from .glossary import GlossaryEntry, format_for_prompt, relevant_entries
from .llm import ChatMessage, ChatRequest, LLMProvider
from .prompts import render

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class TranslationError(Exception):
    pass


class TranslationPaused(Exception):
    """Manual pause between batches; completed batches are already on disk."""


class TranslationCanceled(Exception):
    """Manual cancel between batches; completed batches are already on disk."""


@dataclass
class TranslationSettings:
    source_language: str
    target_language: str
    model: str
    batch_size: int = 20
    context_tail: int = 3
    style: str = ""
    temperature: float | None = None


def _load_partial(partial_path: Path) -> list[dict]:
    if not partial_path.exists():
        return []
    return json.loads(partial_path.read_text(encoding="utf-8"))


def parse_translation_response(content: str, expected_ids: list[int]) -> dict[int, str]:
    match = _ARRAY_RE.search(content)
    if not match:
        raise TranslationError("response contains no JSON array")
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise TranslationError(f"response is not valid JSON: {error}") from error
    if not isinstance(items, list):
        raise TranslationError("response JSON is not an array")
    translations: dict[int, str] = {}
    for item in items:
        if not isinstance(item, dict) or "id" not in item or "text" not in item:
            raise TranslationError("response items must have id and text")
        translations[int(item["id"])] = str(item["text"])
    if set(translations) != set(expected_ids):
        raise TranslationError(
            f"response ids {sorted(translations)} != expected {sorted(expected_ids)}"
        )
    return translations


def _context_text(done: list[dict], tail: int) -> str:
    targets = [item["target"] for item in done[-tail:]]
    return "\n".join(targets) if targets else "(none)"


def translate_segments(
    segments: list[dict],
    settings: TranslationSettings,
    provider: LLMProvider,
    meter: BudgetMeter,
    glossary_entries: list[GlossaryEntry],
    template: str,
    *,
    project: str,
    task_id: str,
    partial_path: Path,
    emit_progress: Callable[[int, int], None],
    should_pause: Callable[[], bool] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[dict]:
    done = _load_partial(partial_path)
    done_ids = {item["id"] for item in done}
    pending = [s for s in segments if s["id"] not in done_ids]
    total = len(segments)
    emit_progress(len(done), total)

    for offset in range(0, len(pending), settings.batch_size):
        # Cancel wins over pause: a user who hit both wants it stopped.
        if should_cancel is not None and should_cancel():
            raise TranslationCanceled("manual cancel requested")
        if should_pause is not None and should_pause():
            raise TranslationPaused("manual pause requested")
        batch = pending[offset : offset + settings.batch_size]
        entries = relevant_entries(glossary_entries, [s["text"] for s in batch])
        variables = {
            "source_language": settings.source_language,
            "target_language": settings.target_language,
            "style": settings.style or "(none)",
            "glossary": format_for_prompt(entries),
            "context": _context_text(done, settings.context_tail),
            "segments_json": json.dumps(
                [{"id": s["id"], "text": s["text"]} for s in batch],
                ensure_ascii=False,
            ),
        }
        prompt = render(template, variables)
        request = ChatRequest(
            model=settings.model,
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=settings.temperature,
        )
        response = meter.chat(provider, request, project=project, task_id=task_id)
        expected_ids = [s["id"] for s in batch]
        try:
            translations = parse_translation_response(response.content, expected_ids)
        except TranslationError:
            retry = ChatRequest(
                model=settings.model,
                messages=request.messages
                + [
                    ChatMessage(role="assistant", content=response.content),
                    ChatMessage(
                        role="user",
                        content=(
                            "Your previous reply was not a valid JSON array covering "
                            "every segment id. Return only the JSON array."
                        ),
                    ),
                ],
                temperature=settings.temperature,
            )
            response = meter.chat(provider, retry, project=project, task_id=task_id)
            translations = parse_translation_response(response.content, expected_ids)

        for seg in batch:
            done.append(
                {
                    "id": seg["id"],
                    "start": seg["start"],
                    "end": seg["end"],
                    "source": seg["text"],
                    "target": translations[seg["id"]],
                }
            )
        atomic_write_text(
            partial_path, json.dumps(done, ensure_ascii=False, indent=2)
        )
        emit_progress(len(done), total)

    order = {s["id"]: i for i, s in enumerate(segments)}
    return sorted(done, key=lambda item: order[item["id"]])
