"""faster-whisper adapter. The heavy dependency is imported lazily so the
core package works without the asr extra installed."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .base import AsrError, AsrResult, AsrSegment, register_asr


@register_asr("faster_whisper")
class FasterWhisperProvider:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float, float], None] | None = None,
    ) -> AsrResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise AsrError(
                "faster-whisper is not installed; install the asr extra: "
                "uv sync --extra asr"
            ) from error
        model = WhisperModel(
            self.model_size, device=self.device, compute_type=self.compute_type
        )
        raw_segments, info = model.transcribe(
            str(audio_path), language=language, vad_filter=True
        )
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        segments: list[AsrSegment] = []
        for seg in raw_segments:
            text = seg.text.strip()
            if not text:
                continue
            segments.append(
                AsrSegment(start=float(seg.start), end=float(seg.end), text=text)
            )
            if on_progress and duration:
                on_progress(min(float(seg.end), duration), duration)
        if on_progress and duration:
            on_progress(duration, duration)
        return AsrResult(
            language=getattr(info, "language", None) or "unknown",
            duration=duration,
            segments=segments,
        )
