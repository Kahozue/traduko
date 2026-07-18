"""Chunk translation engine for the document pipeline.

Mirrors traduko.translate: partial results land next to the final
artifact so an interrupted run resumes without re-spending tokens. Each
chunk prompt carries glossary hits, the tail of the previous chunk's
translation, and a rolling summary that an LLM refreshes every
summary_chunks chunks or summary_chars target chars. A chunk whose
response cannot be parsed is retried once with a correction message,
then bisected; a single block that still fails marks the whole chunk
"failed" (qc flags it and export refuses to run until it is fixed).
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..budget import BudgetMeter
from ..fsutil import atomic_write_text
from ..glossary import GlossaryEntry, format_for_prompt, relevant_entries
from ..llm import ChatMessage, ChatRequest, LLMProvider
from ..prompts import render
from ..translate import TranslationError, TranslationPaused
from .model import Block, ChunksDoc, DocTranslationDoc, DocumentDoc, TranslatedBlock, TranslatedChunk

_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class ChunkFailed(Exception):
    """A chunk kept failing after bisection down to single blocks."""


@dataclass
class DocTranslationSettings:
    source_language: str
    target_language: str
    model: str
    context_tail: int = 5
    summary_chunks: int = 10
    summary_chars: int = 16000
    temperature: float | None = None


def parse_chunk_response(content: str, expected_ids: list[str]) -> dict[str, str]:
    match = _ARRAY_RE.search(content)
    if not match:
        raise TranslationError("response contains no JSON array")
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise TranslationError(f"response is not valid JSON: {error}") from error
    if not isinstance(items, list):
        raise TranslationError("response JSON is not an array")
    translations: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict) or "id" not in item or "text" not in item:
            raise TranslationError("response items must have id and text")
        translations[str(item["id"])] = str(item["text"])
    if set(translations) != set(expected_ids):
        raise TranslationError(
            f"response ids {sorted(translations)} != expected {sorted(expected_ids)}"
        )
    return translations


@dataclass
class _SummaryState:
    summary: str = ""
    recent: str = ""
    chunks_since: int = 0
    chars_since: int = 0

    @classmethod
    def load(cls, path: Path) -> _SummaryState:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            summary=data.get("summary", ""),
            recent=data.get("recent", ""),
            chunks_since=data.get("chunks_since", 0),
            chars_since=data.get("chars_since", 0),
        )

    def save(self, path: Path) -> None:
        atomic_write_text(
            path,
            json.dumps(
                {
                    "schema_version": 1,
                    "summary": self.summary,
                    "recent": self.recent,
                    "chunks_since": self.chunks_since,
                    "chars_since": self.chars_since,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )


class _Engine:
    def __init__(
        self,
        settings: DocTranslationSettings,
        provider: LLMProvider,
        meter: BudgetMeter,
        glossary_entries: list[GlossaryEntry],
        translate_template: str,
        summary_template: str,
        project: str,
        task_id: str,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.meter = meter
        self.glossary_entries = glossary_entries
        self.translate_template = translate_template
        self.summary_template = summary_template
        self.project = project
        self.task_id = task_id

    def _chat(self, messages: list[ChatMessage]) -> str:
        request = ChatRequest(
            model=self.settings.model,
            messages=messages,
            temperature=self.settings.temperature,
        )
        response = self.meter.chat(
            self.provider, request, project=self.project, task_id=self.task_id
        )
        return response.content

    def _attempt(
        self, blocks: list[Block], summary: str, context: str
    ) -> dict[str, str]:
        entries = relevant_entries(self.glossary_entries, [b.text for b in blocks])
        prompt = render(
            self.translate_template,
            {
                "source_language": self.settings.source_language,
                "target_language": self.settings.target_language,
                "glossary": format_for_prompt(entries),
                "summary": summary or "(none)",
                "context": context or "(none)",
                "blocks_json": json.dumps(
                    [{"id": b.id, "text": b.text} for b in blocks],
                    ensure_ascii=False,
                ),
            },
        )
        messages = [ChatMessage(role="user", content=prompt)]
        content = self._chat(messages)
        expected_ids = [b.id for b in blocks]
        try:
            return parse_chunk_response(content, expected_ids)
        except TranslationError:
            retry = messages + [
                ChatMessage(role="assistant", content=content),
                ChatMessage(
                    role="user",
                    content=(
                        "Your previous reply was not a valid JSON array covering "
                        "every block id. Return only the JSON array."
                    ),
                ),
            ]
            return parse_chunk_response(self._chat(retry), expected_ids)

    def translate_blocks(
        self, blocks: list[Block], summary: str, context: str
    ) -> dict[str, str]:
        try:
            return self._attempt(blocks, summary, context)
        except TranslationError as error:
            if len(blocks) == 1:
                raise ChunkFailed(str(error)) from error
            mid = len(blocks) // 2
            first = self.translate_blocks(blocks[:mid], summary, context)
            second = self.translate_blocks(blocks[mid:], summary, context)
            return {**first, **second}

    def update_summary(self, state: _SummaryState) -> None:
        prompt = render(
            self.summary_template,
            {
                "target_language": self.settings.target_language,
                "summary": state.summary or "(none)",
                "recent_text": state.recent,
            },
        )
        state.summary = self._chat([ChatMessage(role="user", content=prompt)]).strip()
        state.recent = ""
        state.chunks_since = 0
        state.chars_since = 0


def _load_partial(partial_path: Path) -> dict[str, TranslatedChunk]:
    if not partial_path.exists():
        return {}
    items = json.loads(partial_path.read_text(encoding="utf-8"))
    chunks = [TranslatedChunk.model_validate(item) for item in items]
    # The cache exists to avoid re-spending tokens on successes; failed
    # chunks are dropped so a resumed run re-attempts them.
    return {chunk.id: chunk for chunk in chunks if chunk.status == "translated"}


def _save_partial(partial_path: Path, done: list[TranslatedChunk]) -> None:
    atomic_write_text(
        partial_path,
        json.dumps(
            [chunk.model_dump() for chunk in done], ensure_ascii=False, indent=2
        ),
    )


def translate_document_chunks(
    document: DocumentDoc,
    chunks: ChunksDoc,
    settings: DocTranslationSettings,
    provider: LLMProvider,
    meter: BudgetMeter,
    glossary_entries: list[GlossaryEntry],
    translate_template: str,
    summary_template: str,
    *,
    project: str,
    task_id: str,
    partial_path: Path,
    summary_path: Path,
    emit_progress: Callable[[int, int], None],
    should_pause: Callable[[], bool] | None = None,
    retry_ids: set[str] | None = None,
    prior: DocTranslationDoc | None = None,
) -> DocTranslationDoc:
    engine = _Engine(
        settings,
        provider,
        meter,
        glossary_entries,
        translate_template,
        summary_template,
        project,
        task_id,
    )
    blocks_by_id = {
        block.id: block
        for chapter in document.chapters
        for block in chapter.blocks
    }
    prior_by_id = {chunk.id: chunk for chunk in prior.chunks} if prior else {}
    partial = _load_partial(partial_path)
    state = _SummaryState.load(summary_path)

    results: list[TranslatedChunk] = []
    total = len(chunks.chunks)
    completed = 0
    emit_progress(completed, total)

    for chunk in chunks.chunks:
        if retry_ids is not None and chunk.id not in retry_ids:
            carried = prior_by_id.get(
                chunk.id, TranslatedChunk(id=chunk.id, status="pending", blocks=[])
            )
            results.append(carried)
            completed += 1
            emit_progress(completed, total)
            continue
        if chunk.id in partial:
            results.append(partial[chunk.id])
            completed += 1
            emit_progress(completed, total)
            continue
        if should_pause is not None and should_pause():
            raise TranslationPaused("manual pause requested")

        previous = results[-1] if results else None
        context = ""
        if previous is not None and previous.status == "translated":
            tail = previous.blocks[-settings.context_tail :]
            context = "\n".join(block.text for block in tail)

        blocks = [blocks_by_id[i] for i in chunk.block_ids if i in blocks_by_id]
        try:
            translations = engine.translate_blocks(blocks, state.summary, context)
            translated = TranslatedChunk(
                id=chunk.id,
                status="translated",
                blocks=[
                    TranslatedBlock(id=block.id, text=translations[block.id])
                    for block in blocks
                ],
            )
        except ChunkFailed:
            translated = TranslatedChunk(id=chunk.id, status="failed", blocks=[])

        results.append(translated)
        partial[chunk.id] = translated
        _save_partial(partial_path, [c for c in results if c.id in partial])
        completed += 1
        emit_progress(completed, total)

        if translated.status == "translated":
            chunk_text = "\n".join(block.text for block in translated.blocks)
            state.recent = f"{state.recent}\n{chunk_text}" if state.recent else chunk_text
            state.chunks_since += 1
            state.chars_since += len(chunk_text)
            if (
                state.chunks_since >= settings.summary_chunks
                or state.chars_since >= settings.summary_chars
            ):
                engine.update_summary(state)
            state.save(summary_path)

    return DocTranslationDoc(chunks=results)
