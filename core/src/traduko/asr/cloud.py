"""OpenAI-compatible cloud transcription provider.

One provider class serves whisper-1, the gpt-4o transcribe family and
custom OpenAI-compatible endpoints (Groq, Qwen ASR, ...); the engine
layer picks the model and response mode. Long inputs are chunked at
silence boundaries into 16 kHz mono FLAC uploads (25 MB API cap; the
gpt-4o family also caps audio context at ~15 minutes per request).
"""
from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from ..media import (
    build_chunk_flac_cmd,
    build_silence_detect_cmd,
    parse_silences,
    plan_chunks,
    probe_duration,
    run as run_media,
    run_capture_stderr,
)
from .base import AsrError, AsrResult, AsrSegment, register_asr

# Chunking policy per model family (seconds).
_GPT4O_TARGET = 720.0
_GPT4O_HARD_MAX = 840.0
_WHISPER_TARGET = 600.0
_WHISPER_HARD_MAX = 1200.0
_SIZE_LIMIT_BYTES = 24 * 1024 * 1024

_ZH_PROMPT = "以下是普通話或華語的內容，請以繁體中文輸出文字。"
_PROMPT_TAIL_CHARS = 200

_RETRY_STATUS = {429, 500, 502, 503, 504}


@register_asr("openai_cloud")
class OpenAICloudProvider:
    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        api_key_env: str = "",
        model: str = "whisper-1",
        mode: str = "verbose",  # verbose | diarize | text | auto
        zh_prompt: bool = True,
        timeout: float = 600.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key and api_key_env:
            api_key = os.environ.get(api_key_env, "")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.mode = mode
        self.zh_prompt = zh_prompt
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._client = httpx.Client(timeout=timeout, transport=transport)
        # Injectable for tests: Path -> ([(chunk_path, offset_seconds)], total).
        self._prepare: Callable[[Path], tuple[list[tuple[Path, float]], float]] = (
            self._prepare_chunks
        )

    # -- chunk preparation ---------------------------------------------------

    def _limits(self) -> tuple[float, float]:
        if self.model.startswith("gpt-4o"):
            return _GPT4O_TARGET, _GPT4O_HARD_MAX
        return _WHISPER_TARGET, _WHISPER_HARD_MAX

    def _prepare_chunks(
        self, audio_path: Path
    ) -> tuple[list[tuple[Path, float]], float]:
        duration = probe_duration(audio_path)
        target, hard_max = self._limits()
        size_ok = audio_path.stat().st_size <= _SIZE_LIMIT_BYTES
        if duration <= hard_max and size_ok:
            return [(audio_path, 0.0)], duration
        silences = parse_silences(
            run_capture_stderr(build_silence_detect_cmd(audio_path))
        )
        spans = plan_chunks(duration, silences, target=target, hard_max=hard_max)
        tmp_dir = Path(tempfile.mkdtemp(prefix="traduko-asr-"))
        chunks: list[tuple[Path, float]] = []
        for index, (start, end) in enumerate(spans):
            out = tmp_dir / f"chunk-{index:03d}.flac"
            run_media(build_chunk_flac_cmd(audio_path, start, end - start, out))
            chunks.append((out, start))
        return chunks, duration

    # -- HTTP ----------------------------------------------------------------

    def _response_format(self, mode: str) -> str:
        if mode in ("verbose", "auto"):
            return "verbose_json"
        if mode == "diarize":
            return "diarized_json"
        return "json"

    def _post_chunk(
        self, chunk_path: Path, *, mode: str, prompt: str, language: str | None
    ) -> httpx.Response:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data: dict = {
            "model": self.model,
            "response_format": self._response_format(mode),
        }
        if prompt:
            data["prompt"] = prompt
        if language:
            data["language"] = language
        files = {"file": (chunk_path.name, chunk_path.read_bytes(), "audio/flac")}
        last_error = ""
        for attempt in range(self.max_retries + 1):
            if attempt:
                time.sleep(self.backoff_base * (2 ** (attempt - 1)))
            try:
                response = self._client.post(
                    f"{self.base_url}/audio/transcriptions",
                    data=data,
                    files=files,
                    headers=headers,
                )
            except httpx.TransportError as error:
                last_error = str(error)
                continue
            if response.status_code in _RETRY_STATUS:
                last_error = f"http {response.status_code}"
                continue
            return response
        raise AsrError(
            f"cloud asr failed after {self.max_retries + 1} attempts: {last_error}"
        )

    # -- transcription -------------------------------------------------------

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        on_progress: Callable[[float, float], None] | None = None,
        glossary_terms: list[str] | None = None,
    ) -> AsrResult:
        if not self.api_key and "api.openai.com" in self.base_url:
            raise AsrError(
                "OpenAI API key is not configured; set it in the settings "
                "speech-recognition section"
            )
        chunks, total_duration = self._prepare(audio_path)
        mode = self.mode
        segments: list[AsrSegment] = []
        detected_language = language or ""
        timestamps = mode not in ("text",)
        previous_text = ""
        for index, (chunk_path, offset) in enumerate(chunks):
            prompt_parts = []
            if glossary_terms:
                prompt_parts.append(" ".join(glossary_terms))
            if self.zh_prompt and (language or "").startswith("zh"):
                prompt_parts.append(_ZH_PROMPT)
            if previous_text:
                prompt_parts.append(previous_text[-_PROMPT_TAIL_CHARS:])
            response = self._post_chunk(
                chunk_path,
                mode=mode,
                prompt=" ".join(prompt_parts),
                language=language,
            )
            if response.status_code == 400 and mode == "auto":
                # Custom endpoint without verbose_json support: drop to plain
                # text for the rest of the file.
                mode = "text"
                timestamps = False
                response = self._post_chunk(
                    chunk_path,
                    mode=mode,
                    prompt=" ".join(prompt_parts),
                    language=language,
                )
            if response.status_code != 200:
                raise AsrError(
                    f"cloud asr failed: http {response.status_code}: "
                    f"{response.text[:200]}"
                )
            payload = response.json()
            detected_language = payload.get("language") or detected_language
            raw_segments = payload.get("segments")
            if raw_segments is None and mode == "auto":
                # 200 but plain shape: endpoint ignored verbose_json.
                mode = "text"
                timestamps = False
            if raw_segments:
                for seg in raw_segments:
                    text = str(seg.get("text", "")).strip()
                    if not text:
                        continue
                    segments.append(
                        AsrSegment(
                            start=float(seg.get("start", 0.0)) + offset,
                            end=float(seg.get("end", 0.0)) + offset,
                            speaker=seg.get("speaker"),
                            text=text,
                        )
                    )
                previous_text = str(payload.get("text", "")) or " ".join(
                    str(seg.get("text", "")) for seg in raw_segments
                )
            else:
                text = str(payload.get("text", "")).strip()
                if text:
                    segments.append(
                        AsrSegment(start=offset, end=offset, text=text)
                    )
                previous_text = text
            if on_progress and total_duration:
                covered = (
                    chunks[index + 1][1]
                    if index + 1 < len(chunks)
                    else total_duration
                )
                on_progress(min(covered, total_duration), total_duration)
        if mode == "text":
            timestamps = False
        return AsrResult(
            language=detected_language or "unknown",
            duration=total_duration,
            segments=segments,
            timestamps=timestamps,
        )
