"""export_transcript / export_audio stage tests."""
from pathlib import Path

import pytest

from traduko.stages import base, registry
from test_stages_av import make_ctx


def write_asr(ctx, *, timestamps=True, speakers=False):
    segments = [
        {"id": 1, "start": 1.0, "end": 2.5, "text": "こんにちは"},
        {"id": 2, "start": 3.0, "end": 4.0, "text": "元気ですか"},
    ]
    if speakers:
        segments[0]["speaker"] = "A"
        segments[1]["speaker"] = "B"
    ctx.artifacts.write_json(
        1,
        "asr.json",
        {
            "language": "ja",
            "duration": 4.0,
            "timestamps": timestamps,
            "segments": segments,
        },
    )


def test_export_transcript_from_asr_with_timestamps(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.wav", stage_index=1)
    write_asr(ctx)
    result = registry.create("export_transcript").run(ctx)
    assert result.artifacts == ["02-transcript.txt"]
    body = ctx.artifacts.latest_path("transcript.txt").read_text(encoding="utf-8")
    assert "[00:00:01 → 00:00:02] こんにちは" in body
    assert "元気ですか" in body


def test_export_transcript_timestampless_auto_is_plain(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.wav", stage_index=1)
    write_asr(ctx, timestamps=False)
    registry.create("export_transcript").run(ctx)
    body = ctx.artifacts.latest_path("transcript.txt").read_text(encoding="utf-8")
    assert "[" not in body
    assert body.splitlines()[0] == "こんにちは"


def test_export_transcript_speaker_prefix_and_off_param(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path, tmp_path / "in.wav", stage_index=1, params={"timestamps": "off"}
    )
    write_asr(ctx, speakers=True)
    registry.create("export_transcript").run(ctx)
    body = ctx.artifacts.latest_path("transcript.txt").read_text(encoding="utf-8")
    assert body.splitlines()[0] == "A：こんにちは"
    assert "[" not in body


def test_export_transcript_prefers_translation(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.wav", stage_index=2)
    write_asr(ctx)
    ctx.artifacts.write_json(
        2,
        "translation.json",
        {
            "source_language": "ja",
            "target_language": "zh-TW",
            "segments": [
                {"id": 1, "start": 1.0, "end": 2.5, "source": "こんにちは", "target": "你好"},
            ],
        },
    )
    registry.create("export_transcript").run(ctx)
    body = ctx.artifacts.latest_path("transcript.txt").read_text(encoding="utf-8")
    assert "你好" in body
    assert "こんにちは" not in body


def test_export_transcript_markdown_format(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path, tmp_path / "in.wav", stage_index=1, params={"format": "md"}
    )
    write_asr(ctx, speakers=True)
    result = registry.create("export_transcript").run(ctx)
    assert result.artifacts == ["02-transcript.md"]
    body = ctx.artifacts.latest_path("transcript.md").read_text(encoding="utf-8")
    assert "**A**" in body


def test_export_transcript_without_sources_fails(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.wav", stage_index=1)
    with pytest.raises(base.StageError):
        registry.create("export_transcript").run(ctx)


def test_export_audio_encodes_dub_mix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.audio.ffmpeg_available", lambda: True)
    commands: list[list[str]] = []

    def fake_run(cmd):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"audio")

    monkeypatch.setattr("traduko.stages.audio.run_media", fake_run)
    ctx, progress = make_ctx(tmp_path, tmp_path / "in.wav", stage_index=5)
    mix = ctx.artifacts.path_for(5, "dub-mix.wav")
    mix.parent.mkdir(parents=True, exist_ok=True)
    mix.write_bytes(b"RIFF")
    result = registry.create("export_audio").run(ctx)
    assert result.artifacts == ["06-audio-dubbed.m4a"]
    assert commands[0][0] == "ffmpeg"
    assert "aac" in commands[0]
    assert progress == [(1, 1)]


def test_export_audio_requires_dub_mix(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.audio.ffmpeg_available", lambda: True)
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.wav", stage_index=1)
    with pytest.raises(base.StageError, match="dub-mix"):
        registry.create("export_audio").run(ctx)
