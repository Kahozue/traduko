"""Audiovisual pipeline stages.

Convention: a stage reads its input artifact by name (latest numbered
match) and writes artifacts numbered stage_index + 1, so profiles can
insert or remove stages without breaking neighbours.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from ..asr import AsrError, create_asr
from ..budget import BudgetExceededError, BudgetMeter
from ..config import load_config
from ..fsutil import atomic_write_text
from ..glossary import load_glossary
from ..llm import LLMError
from ..media import (
    MediaError,
    build_extract_audio_cmd,
    build_hardburn_cmd,
    ffmpeg_available,
)
from ..media import run as run_media
from ..prompts import load_template
from ..segmenting import refine_segments
from ..styles import SubtitleStyle, serialize_ass
from ..subtitles import (
    Cue,
    SubtitleError,
    compose_bilingual,
    parse_subtitle,
    serialize_srt,
    serialize_txt,
    serialize_vtt,
)
from ..translate import (
    TranslationError,
    TranslationPaused,
    TranslationSettings,
    translate_segments,
)
from . import registry
from .base import PauseRequested, StageContext, StageError, StageResult
from .common import resolve_llm


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
        provider, model = resolve_llm(ctx.params, config)

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
                should_pause=ctx.should_pause,
            )
        except BudgetExceededError as error:
            raise PauseRequested(str(error)) from error
        except TranslationPaused as error:
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


def _style_from(ctx: StageContext) -> SubtitleStyle:
    base_values: dict = {}
    preset = ctx.params.get("style_preset")
    if preset:
        path = ctx.data_root / "config" / "styles.yaml"
        presets = {}
        if path.exists():
            presets = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if preset not in presets:
            raise StageError(f"unknown style preset: {preset}")
        base_values = dict(presets[preset])
    base_values.update(ctx.params.get("style") or {})
    return SubtitleStyle(**base_values)


def _cues_from_translation(data: dict, bilingual: bool) -> list[Cue]:
    cues: list[Cue] = []
    for seg in data["segments"]:
        text = (
            compose_bilingual(seg["target"], seg["source"])
            if bilingual
            else seg["target"]
        )
        cues.append(Cue(id=seg["id"], start=seg["start"], end=seg["end"], text=text))
    return cues


_SERIALIZERS = {
    "srt": lambda cues, ctx: serialize_srt(cues),
    "vtt": lambda cues, ctx: serialize_vtt(cues),
    "txt": lambda cues, ctx: serialize_txt(cues),
    "ass": lambda cues, ctx: serialize_ass(cues, _style_from(ctx)),
}


@registry.register
class ExportSubtitlesStage:
    type = "export_subtitles"

    def run(self, ctx: StageContext) -> StageResult:
        try:
            data = ctx.artifacts.read_latest_json("translation.json")
        except FileNotFoundError as error:
            raise StageError("export stage requires a translation artifact") from error
        formats = ctx.params.get("formats", ["srt"])
        cues = _cues_from_translation(data, ctx.params.get("bilingual", False))
        names: list[str] = []
        for fmt in formats:
            serializer = _SERIALIZERS.get(fmt)
            if serializer is None:
                raise StageError(f"unknown subtitle format: {fmt}")
            try:
                body = serializer(cues, ctx)
            except SubtitleError as error:
                raise StageError(str(error)) from error
            path = ctx.artifacts.path_for(ctx.stage_index + 1, f"subtitles.{fmt}")
            atomic_write_text(path, body)
            names.append(path.name)
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=names)


@registry.register
class HardburnStage:
    type = "hardburn"

    def run(self, ctx: StageContext) -> StageResult:
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        try:
            data = ctx.artifacts.read_latest_json("translation.json")
        except FileNotFoundError as error:
            raise StageError("hardburn stage requires a translation artifact") from error
        cues = _cues_from_translation(data, ctx.params.get("bilingual", False))
        try:
            body = serialize_ass(cues, _style_from(ctx))
        except SubtitleError as error:
            raise StageError(str(error)) from error
        ass_path = ctx.artifacts.path_for(ctx.stage_index + 1, "burn.ass")
        atomic_write_text(ass_path, body)
        output = ctx.artifacts.path_for(
            ctx.stage_index + 1, ctx.params.get("output_name", "video.mp4")
        )
        fonts_dir = ctx.params.get("fonts_dir")
        try:
            run_media(
                build_hardburn_cmd(
                    Path(ctx.task.input_path),
                    ass_path,
                    output,
                    fonts_dir=Path(fonts_dir) if fonts_dir else None,
                )
            )
        except MediaError as error:
            raise StageError(str(error)) from error
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[ass_path.name, output.name])
