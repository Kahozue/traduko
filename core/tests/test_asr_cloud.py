"""openai_cloud ASR provider tests: all HTTP via MockTransport, chunking
injected so no ffmpeg runs."""
from pathlib import Path

import httpx
import pytest

from traduko.asr import AsrError, create_asr


def make_provider(handler, *, mode="verbose", model="whisper-1", **kwargs):
    return create_asr(
        "openai_cloud",
        base_url="https://api.openai.com/v1",
        api_key=kwargs.pop("api_key", "sk-test"),
        model=model,
        mode=mode,
        transport=httpx.MockTransport(handler),
        backoff_base=0.0,
        **kwargs,
    )


def single_chunk(path: Path, duration: float = 30.0):
    def prepare(audio_path: Path):
        return [(audio_path, 0.0)], duration

    return prepare


def make_audio(tmp_path: Path) -> Path:
    path = tmp_path / "in.wav"
    path.write_bytes(b"RIFFfakewav")
    return path


VERBOSE_BODY = {
    "task": "transcribe",
    "language": "zh",
    "duration": 30.0,
    "text": "你好 世界",
    "segments": [
        {"id": 0, "start": 0.0, "end": 2.0, "text": "你好"},
        {"id": 1, "start": 2.0, "end": 4.0, "text": "世界"},
    ],
}


def test_verbose_mode_maps_segments(tmp_path: Path) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = request.read()
        return httpx.Response(200, json=VERBOSE_BODY)

    provider = make_provider(handler)
    provider._prepare = single_chunk(make_audio(tmp_path))
    result = provider.transcribe(make_audio(tmp_path))
    assert captured["url"].endswith("/audio/transcriptions")
    assert captured["auth"] == "Bearer sk-test"
    assert b'name="model"' in captured["body"]
    assert b"whisper-1" in captured["body"]
    assert b"verbose_json" in captured["body"]
    assert result.language == "zh"
    assert result.timestamps is True
    assert [s.text for s in result.segments] == ["你好", "世界"]
    assert result.segments[1].start == 2.0


def test_text_mode_single_segment_without_timestamps(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert b'name="response_format"' in request.read()
        return httpx.Response(200, json={"text": "plain transcript"})

    provider = make_provider(handler, mode="text", model="gpt-4o-transcribe")
    provider._prepare = single_chunk(make_audio(tmp_path))
    result = provider.transcribe(make_audio(tmp_path))
    assert result.timestamps is False
    assert len(result.segments) == 1
    assert result.segments[0].text == "plain transcript"


def test_diarize_mode_keeps_speaker_labels(tmp_path: Path) -> None:
    body = {
        "duration": 10.0,
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "hello", "speaker": "A"},
            {"start": 3.0, "end": 6.0, "text": "hi", "speaker": "B"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"diarized_json" in request.read()
        return httpx.Response(200, json=body)

    provider = make_provider(handler, mode="diarize", model="gpt-4o-transcribe-diarize")
    provider._prepare = single_chunk(make_audio(tmp_path))
    result = provider.transcribe(make_audio(tmp_path))
    assert result.timestamps is True
    assert [s.speaker for s in result.segments] == ["A", "B"]


def test_chunks_shift_offsets_and_chain_prompts(tmp_path: Path) -> None:
    bodies = iter(
        [
            {
                "language": "zh",
                "duration": 600.0,
                "text": "第一塊結尾句",
                "segments": [{"start": 0.0, "end": 5.0, "text": "第一塊結尾句"}],
            },
            {
                "language": "zh",
                "duration": 30.0,
                "text": "第二塊",
                "segments": [{"start": 1.0, "end": 3.0, "text": "第二塊"}],
            },
        ]
    )
    requests: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.read())
        return httpx.Response(200, json=next(bodies))

    provider = make_provider(handler)
    first = make_audio(tmp_path)
    second = tmp_path / "chunk2.flac"
    second.write_bytes(b"flacdata")
    provider._prepare = lambda path: ([(first, 0.0), (second, 600.0)], 630.0)
    progress: list[tuple[float, float]] = []
    result = provider.transcribe(
        first, language="zh", on_progress=lambda c, t: progress.append((c, t))
    )
    assert [s.start for s in result.segments] == [0.0, 601.0]
    # Continuation: the second request's prompt carries the first chunk's tail.
    assert "第一塊結尾句".encode() in requests[1]
    # zh prompt bias present on the first request too.
    assert "繁體中文".encode() in requests[0]
    assert progress[-1] == (630.0, 630.0)


def test_missing_openai_key_raises(tmp_path: Path) -> None:
    provider = make_provider(lambda request: httpx.Response(200), api_key="")
    provider._prepare = single_chunk(make_audio(tmp_path))
    with pytest.raises(AsrError):
        provider.transcribe(make_audio(tmp_path))


def test_retry_on_429_then_success(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "slow down"})
        return httpx.Response(200, json=VERBOSE_BODY)

    provider = make_provider(handler)
    provider._prepare = single_chunk(make_audio(tmp_path))
    result = provider.transcribe(make_audio(tmp_path))
    assert calls["n"] == 2
    assert result.segments


def test_auto_mode_falls_back_to_plain_text(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if b"verbose_json" in request.read():
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return httpx.Response(200, json={"text": "custom endpoint text"})

    provider = make_provider(handler, mode="auto", model="whisper-large-v3")
    provider._prepare = single_chunk(make_audio(tmp_path))
    result = provider.transcribe(make_audio(tmp_path))
    assert result.timestamps is False
    assert result.segments[0].text == "custom endpoint text"
