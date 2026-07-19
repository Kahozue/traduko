"""Audio-domain output stages: plain transcripts and dubbed audio files."""
from __future__ import annotations

from ..fsutil import atomic_write_text
from ..media import MediaError, build_encode_audio_cmd, ffmpeg_available
from ..media import run as run_media
from . import registry
from .base import StageContext, StageError, StageResult


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


@registry.register
class ExportTranscriptStage:
    type = "export_transcript"

    def run(self, ctx: StageContext) -> StageResult:
        # Fallback chain segments.diarized.json -> translation.json ->
        # asr.json: the diarized doc carries speakers (and the translation
        # when one happened), the translation the target text, the raw asr
        # the source transcript — the same stage closes every pipeline shape.
        diarized = None
        translation = None
        try:
            diarized = ctx.artifacts.read_latest_json("segments.diarized.json")
        except FileNotFoundError:
            try:
                translation = ctx.artifacts.read_latest_json("translation.json")
            except FileNotFoundError:
                pass
        if diarized is not None:
            # Per segment: the translation when present, the source otherwise.
            segments = [
                {**seg, "text": seg.get("target") or seg.get("source", "")}
                for seg in diarized["segments"]
            ]
            text_key = "text"
            has_timestamps = True
        elif translation is not None:
            segments = translation["segments"]
            text_key = "target"
            has_timestamps = True
        else:
            try:
                asr = ctx.artifacts.read_latest_json("asr.json")
            except FileNotFoundError as error:
                raise StageError(
                    "export_transcript needs an asr or translation artifact"
                ) from error
            segments = asr["segments"]
            text_key = "text"
            has_timestamps = asr.get("timestamps", True) is not False

        mode = str(ctx.params.get("timestamps", "auto"))
        include_ts = mode == "on" or (mode == "auto" and has_timestamps)
        fmt = str(ctx.params.get("format", "txt"))
        if fmt not in ("txt", "md"):
            raise StageError(f"unknown transcript format: {fmt}")

        lines: list[str] = []
        for segment in segments:
            text = str(segment.get(text_key, "")).strip()
            if not text:
                continue
            prefix = ""
            if include_ts:
                prefix += (
                    f"[{_format_timestamp(float(segment.get('start', 0.0)))} → "
                    f"{_format_timestamp(float(segment.get('end', 0.0)))}] "
                )
            speaker = segment.get("speaker")
            if speaker:
                prefix += f"**{speaker}**：" if fmt == "md" else f"{speaker}："
            lines.append(prefix + text)
        separator = "\n\n" if fmt == "md" else "\n"
        path = ctx.artifacts.path_for(ctx.stage_index + 1, f"transcript.{fmt}")
        atomic_write_text(path, separator.join(lines) + "\n")
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[path.name])


_AUDIO_CODECS = {"m4a", "mp3", "wav"}


@registry.register
class ExportAudioStage:
    type = "export_audio"

    def run(self, ctx: StageContext) -> StageResult:
        if not ffmpeg_available():
            raise StageError("ffmpeg/ffprobe not found on PATH")
        try:
            mix_path = ctx.artifacts.latest_path("dub-mix.wav")
        except FileNotFoundError as error:
            raise StageError(
                "export_audio needs a dub-mix.wav artifact (run the dubbing "
                "stages first)"
            ) from error
        fmt = str(ctx.params.get("format", "m4a"))
        if fmt not in _AUDIO_CODECS:
            raise StageError(f"unknown audio format: {fmt}")
        output = ctx.artifacts.path_for(
            ctx.stage_index + 1, ctx.params.get("output_name", f"audio-dubbed.{fmt}")
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_media(build_encode_audio_cmd(mix_path, output, fmt))
        except MediaError as error:
            raise StageError(str(error)) from error
        ctx.emit_progress(1, 1)
        return StageResult(artifacts=[output.name])
