"""Export-studio stages.

Each export the user starts appends a fresh stage instance carrying a
snapshot of the panel parameters, so re-exporting with other settings never
rewrites an earlier result: outputs are named export-{seq}.{ext} with a
sequence independent of the stage number.

The pipeline-seeded exports (export_subtitles, export_audio) are unrelated
and keep their own fixed parameters.
"""
from __future__ import annotations

from pathlib import Path

from ..fsutil import atomic_write_text
from ..media import (
    AUDIO_CODECS,
    AUDIO_FORMAT_CODECS,
    AUDIO_TRACK_MODES,
    SUBTITLE_MODES,
    VIDEO_CODECS,
    ExportAudioParams,
    ExportVideoParams,
    MediaError,
    build_export_audio_custom_cmd,
    build_export_video_cmd,
    ffmpeg_available,
)
from ..media import run as run_media
from ..styles import serialize_ass
from ..subtitles import Cue, SubtitleError, compose_bilingual
from . import registry
from .av import _style_from
from .base import StageContext, StageError, StageResult

VIDEO_CONTAINERS = ("mp4", "mkv", "webm")


def _next_export_seq(ctx: StageContext) -> int:
    """Sequence across every export this task has produced, regardless of
    which stage instance wrote it."""
    if not ctx.artifacts.dir.exists():
        return 1
    return len(list(ctx.artifacts.dir.glob("*-export-*"))) + 1


def _int_param(params: dict, name: str, default: int | None) -> int | None:
    value = params.get(name, default)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise StageError(f"{name} must be a number, got {value!r}") from error


def video_params_from(params: dict) -> ExportVideoParams:
    subtitles = str(params.get("subtitles") or "none")
    if subtitles not in SUBTITLE_MODES:
        raise StageError(f"unknown subtitles mode: {subtitles}")
    audio_track = str(params.get("audio_track") or "original")
    if audio_track not in AUDIO_TRACK_MODES:
        raise StageError(f"unknown audio track mode: {audio_track}")
    video_codec = str(params.get("video_codec") or "libx264")
    if video_codec not in VIDEO_CODECS:
        raise StageError(f"unknown video codec: {video_codec}")
    audio_codec = str(params.get("audio_codec") or "aac")
    if audio_codec not in AUDIO_CODECS:
        raise StageError(f"unknown audio codec: {audio_codec}")
    return ExportVideoParams(
        width=_int_param(params, "width", None),
        height=_int_param(params, "height", None),
        crf=_int_param(params, "crf", 20) or 20,
        audio_track=audio_track,
        subtitles=subtitles,
        subtitle_style=params.get("style_preset"),
        video_codec=video_codec,
        video_bitrate_kbps=_int_param(params, "video_bitrate_kbps", None),
        fps=_int_param(params, "fps", None),
        audio_codec=audio_codec,
        audio_bitrate_kbps=_int_param(params, "audio_bitrate_kbps", 192) or 192,
        sample_rate=_int_param(params, "sample_rate", None),
        channels=_int_param(params, "channels", None),
    )


def audio_params_from(params: dict) -> ExportAudioParams:
    fmt = str(params.get("format") or "m4a")
    if fmt not in AUDIO_FORMAT_CODECS:
        raise StageError(f"unknown audio format: {fmt}")
    source = str(params.get("source") or "dub")
    if source not in ("dub", "original"):
        raise StageError(f"unknown audio source: {source}")
    return ExportAudioParams(
        fmt=fmt,
        source=source,
        bitrate_kbps=_int_param(params, "bitrate_kbps", 192) or 192,
        sample_rate=_int_param(params, "sample_rate", None),
        channels=_int_param(params, "channels", None),
    )


def _subtitle_cues(ctx: StageContext, mode: str) -> list[Cue]:
    """Target and bilingual need a translation; source text can also come
    from the untranslated transcript of an STT-only task."""
    names = ["translation.json"] if mode != "source" else [
        "translation.json", "segments.json", "asr.json"
    ]
    data = None
    for name in names:
        try:
            data = ctx.artifacts.read_latest_json(name)
            break
        except FileNotFoundError:
            continue
    if data is None:
        raise StageError(
            f"subtitles={mode} requires a translation or transcript artifact"
        )
    cues: list[Cue] = []
    for seg in data["segments"]:
        source = seg.get("source", seg.get("text", ""))
        target = seg.get("target", "")
        if mode == "source":
            text = source
        elif mode == "bilingual":
            text = compose_bilingual(target, source)
        else:
            text = target
        if not str(text).strip():
            continue
        cues.append(
            Cue(
                id=seg["id"],
                start=seg.get("start"),
                end=seg.get("end"),
                text=text,
            )
        )
    if not cues:
        raise StageError(f"no subtitle text available for subtitles={mode}")
    return cues


@registry.register
class ExportVideoStage:
    type = "export_video"

    def run(self, ctx: StageContext) -> StageResult:
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        params = video_params_from(ctx.params)
        container = str(ctx.params.get("container") or "mp4")
        if container not in VIDEO_CONTAINERS:
            raise StageError(f"unknown container: {container}")
        input_path = Path(ctx.task.input_path)
        if not input_path.exists():
            raise StageError(f"input file is missing: {input_path}")

        dub_audio: Path | None = None
        if params.audio_track == "dub":
            try:
                dub_audio = ctx.artifacts.latest_path("dub-mix.wav")
            except FileNotFoundError as error:
                raise StageError(
                    "the dubbed audio track needs a dub-mix.wav artifact "
                    "(run the dubbing stages first)"
                ) from error

        seq = _next_export_seq(ctx)
        artifacts: list[str] = []
        ass_path: Path | None = None
        if params.subtitles != "none":
            cues = _subtitle_cues(ctx, params.subtitles)
            try:
                body = serialize_ass(cues, _style_from(ctx))
            except SubtitleError as error:
                raise StageError(str(error)) from error
            ass_path = ctx.artifacts.path_for(ctx.stage_index + 1, f"export-{seq}.ass")
            atomic_write_text(ass_path, body)
            artifacts.append(ass_path.name)

        output = ctx.artifacts.path_for(
            ctx.stage_index + 1, f"export-{seq}.{container}"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        fonts_dir = ctx.params.get("fonts_dir")
        try:
            run_media(
                build_export_video_cmd(
                    input_path,
                    output,
                    params,
                    dub_audio_path=dub_audio,
                    ass_path=ass_path,
                    fonts_dir=Path(fonts_dir) if fonts_dir else None,
                )
            )
        except MediaError as error:
            raise StageError(str(error)) from error
        artifacts.append(output.name)
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=artifacts)


@registry.register
class ExportAudioCustomStage:
    type = "export_audio_custom"

    def run(self, ctx: StageContext) -> StageResult:
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        params = audio_params_from(ctx.params)
        if params.source == "dub":
            try:
                source_path = ctx.artifacts.latest_path("dub-mix.wav")
            except FileNotFoundError as error:
                raise StageError(
                    "the dub mix source needs a dub-mix.wav artifact "
                    "(run the dubbing stages first)"
                ) from error
        else:
            # The original audio comes straight off the task input; the
            # extracted audio.wav is 16 kHz mono for ASR and unfit to export.
            source_path = Path(ctx.task.input_path)
            if not source_path.exists():
                raise StageError(f"input file is missing: {source_path}")

        seq = _next_export_seq(ctx)
        output = ctx.artifacts.path_for(
            ctx.stage_index + 1, f"export-{seq}.{params.fmt}"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_media(build_export_audio_custom_cmd(source_path, output, params))
        except MediaError as error:
            raise StageError(str(error)) from error
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[output.name])
