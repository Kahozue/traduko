"""Audiovisual pipeline stages.

Convention: a stage reads its input artifact by name (latest numbered
match) and writes artifacts numbered stage_index + 1, so profiles can
insert or remove stages without breaking neighbours.
"""
from __future__ import annotations

from pathlib import Path

from ..asr import AsrError, create_asr
from ..budget import BudgetExceededError, BudgetMeter
from ..config import load_config
from ..glossary import load_glossary
from ..llm import LLMError, create_llm
from ..media import MediaError, build_extract_audio_cmd, ffmpeg_available
from ..media import run as run_media
from ..prompts import load_template
from ..segmenting import refine_segments
from ..subtitles import SubtitleError, parse_subtitle
from ..translate import TranslationError, TranslationSettings, translate_segments
from . import registry
from .base import PauseRequested, StageContext, StageError, StageResult


@registry.register
class IngestSubtitleStage:
    type = "ingest_subtitle"

    def run(self, ctx: StageContext) -> StageResult:
        input_path = Path(ctx.task.input_path)
        try:
            cues = parse_subtitle(input_path)
        except (SubtitleError, OSError) as error:
            raise StageError(f"cannot ingest subtitle: {error}") from error
        if not cues:
            raise StageError(f"no subtitle cues found in {input_path}")
        segments = [
            {"id": c.id, "start": c.start, "end": c.end, "text": c.text} for c in cues
        ]
        path = ctx.artifacts.write_json(
            ctx.stage_index + 1,
            "segments.json",
            {
                "language": ctx.params.get("source_language", "unknown"),
                "segments": segments,
            },
        )
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[path.name])


@registry.register
class ExtractAudioStage:
    type = "extract_audio"

    def run(self, ctx: StageContext) -> StageResult:
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        output = ctx.artifacts.path_for(ctx.stage_index + 1, "audio.wav")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_media(build_extract_audio_cmd(Path(ctx.task.input_path), output))
        except MediaError as error:
            raise StageError(str(error)) from error
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[output.name])


@registry.register
class AsrStage:
    type = "asr"

    def run(self, ctx: StageContext) -> StageResult:
        try:
            audio_path = ctx.artifacts.latest_path("audio.wav")
        except FileNotFoundError:
            audio_path = Path(ctx.task.input_path)
        language = ctx.params.get("language")
        if language in ("auto", ""):
            language = None
        try:
            provider = create_asr(
                ctx.params.get("provider", "faster_whisper"),
                **ctx.params.get("options", {}),
            )
            result = provider.transcribe(
                audio_path,
                language=language,
                on_progress=lambda current, total: ctx.emit_progress(
                    round(current), round(total)
                ),
            )
        except AsrError as error:
            raise StageError(str(error)) from error
        segments = [
            {"id": i + 1, "start": s.start, "end": s.end, "text": s.text}
            for i, s in enumerate(result.segments)
        ]
        path = ctx.artifacts.write_json(
            ctx.stage_index + 1,
            "asr.json",
            {
                "language": result.language,
                "duration": result.duration,
                "segments": segments,
            },
        )
        return StageResult(artifacts=[path.name])


@registry.register
class SegmentStage:
    type = "segment"

    def run(self, ctx: StageContext) -> StageResult:
        try:
            data = ctx.artifacts.read_latest_json("asr.json")
        except FileNotFoundError as error:
            raise StageError("segment stage requires an asr artifact") from error
        refined = refine_segments(
            data["segments"],
            max_chars=ctx.params.get("max_chars", 42),
            max_duration=ctx.params.get("max_duration", 7.0),
            merge_gap=ctx.params.get("merge_gap", 0.4),
        )
        path = ctx.artifacts.write_json(
            ctx.stage_index + 1,
            "segments.json",
            {"language": data.get("language", "unknown"), "segments": refined},
        )
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[path.name])


@registry.register
class TranslateStage:
    type = "translate"

    def run(self, ctx: StageContext) -> StageResult:
        try:
            data = ctx.artifacts.read_latest_json("segments.json")
        except FileNotFoundError as error:
            raise StageError("translate stage requires a segments artifact") from error
        target_language = ctx.params.get("target_language")
        if not target_language:
            raise StageError("translate stage requires params.target_language")
        source_language = ctx.params.get("source_language", "auto")
        if source_language == "auto":
            source_language = data.get("language", "unknown")

        config = load_config(ctx.data_root)
        provider_name = ctx.params.get("provider", "fake")
        provider_config = config.llm_providers.get(provider_name)
        if provider_config is None:
            if provider_name == "fake":
                provider_config = {"type": "fake"}
            else:
                raise StageError(
                    f"unknown llm provider: {provider_name} "
                    "(define it under llm_providers in config/core.yaml)"
                )
        provider_config = dict(provider_config)
        default_model = provider_config.pop("model", None)
        model = ctx.params.get("model") or default_model or "fake-model"
        try:
            provider = create_llm(provider_config)
        except LLMError as error:
            raise StageError(str(error)) from error

        meter = BudgetMeter(ctx.data_root, ctx.bus, config)
        settings = TranslationSettings(
            source_language=source_language,
            target_language=target_language,
            model=model,
            batch_size=ctx.params.get("batch_size", 20),
            style=ctx.params.get("style", ""),
            temperature=ctx.params.get("temperature"),
        )
        partial_path = ctx.artifacts.path_for(
            ctx.stage_index + 1, "translation.partial.json"
        )
        partial_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            translated = translate_segments(
                data["segments"],
                settings,
                provider,
                meter,
                load_glossary(ctx.data_root, ctx.task.project),
                load_template(ctx.data_root, "translate"),
                project=ctx.task.project,
                task_id=ctx.task.id,
                partial_path=partial_path,
                emit_progress=ctx.emit_progress,
            )
        except BudgetExceededError as error:
            raise PauseRequested(str(error)) from error
        except (TranslationError, LLMError) as error:
            raise StageError(str(error)) from error

        path = ctx.artifacts.write_json(
            ctx.stage_index + 1,
            "translation.json",
            {
                "source_language": source_language,
                "target_language": target_language,
                "segments": translated,
            },
        )
        return StageResult(artifacts=[path.name, partial_path.name])
