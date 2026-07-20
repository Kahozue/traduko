"""Lightweight one-pass LLM correction of glossary terms in ASR text."""
from __future__ import annotations

import json

from ..budget import BudgetExceededError, BudgetMeter
from ..config import load_config
from ..glossary import (
    format_for_prompt,
    relevant_entries,
    resolve_effective_glossary,
)
from ..llm import ChatMessage, ChatRequest, LLMError
from ..prompts import PromptError, load_template, render
from ..translate import TranslationError, parse_translation_response
from . import registry
from .base import PauseRequested, StageContext, StageError, StageResult
from .common import resolve_llm


@registry.register
class GlossaryProofreadStage:
    type = "glossary_proofread"

    def run(self, ctx: StageContext) -> StageResult:
        try:
            data = ctx.artifacts.read_latest_json("asr.json")
        except FileNotFoundError as error:
            raise StageError(
                "glossary_proofread stage requires an asr artifact"
            ) from error
        segments = data.get("segments")
        if not isinstance(segments, list):
            raise StageError("asr artifact segments must be a list")

        entries = resolve_effective_glossary(ctx.data_root, ctx.task)
        relevant = relevant_entries(
            entries, [str(segment.get("text", "")) for segment in segments]
        )
        matching = [
            segment
            for segment in segments
            if any(entry.source in str(segment.get("text", "")) for entry in relevant)
        ]
        if not matching:
            ctx.emit_progress(1, 1)
            return StageResult()

        config = load_config(ctx.data_root)
        provider, model = resolve_llm(ctx.params, config)
        meter = BudgetMeter(ctx.data_root, ctx.bus, config)
        try:
            template = load_template(ctx.data_root, "glossary_proofread")
        except PromptError as error:
            raise StageError(str(error)) from error

        corrected = [dict(segment) for segment in segments]
        by_id = {int(segment["id"]): segment for segment in corrected}
        batch_size = max(1, int(ctx.params.get("batch_size", 20)))
        total = len(matching)
        ctx.emit_progress(0, total)
        for offset in range(0, total, batch_size):
            ctx.checkpoint()
            batch = matching[offset : offset + batch_size]
            prompt = render(
                template,
                {
                    "source_language": str(data.get("language", "unknown")),
                    "glossary": format_for_prompt(relevant),
                    "segments_json": json.dumps(
                        [
                            {"id": segment["id"], "text": segment.get("text", "")}
                            for segment in batch
                        ],
                        ensure_ascii=False,
                    ),
                },
            )
            request = ChatRequest(
                model=model,
                messages=[ChatMessage(role="user", content=prompt)],
                temperature=ctx.params.get("temperature"),
            )
            try:
                response = meter.chat(
                    provider,
                    request,
                    project=ctx.task.project,
                    task_id=ctx.task.id,
                )
                expected_ids = [int(segment["id"]) for segment in batch]
                replacements = parse_translation_response(
                    response.content, expected_ids
                )
            except BudgetExceededError as error:
                raise PauseRequested(str(error)) from error
            except (LLMError, TranslationError) as error:
                raise StageError(str(error)) from error
            for segment_id, text in replacements.items():
                by_id[segment_id]["text"] = text
            ctx.emit_progress(min(offset + len(batch), total), total)

        path = ctx.artifacts.write_json(
            ctx.stage_index + 1,
            "asr.json",
            {
                "language": data.get("language", "unknown"),
                "duration": data.get("duration", 0.0),
                "timestamps": data.get("timestamps", True),
                "segments": corrected,
            },
        )
        return StageResult(artifacts=[path.name])
