from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.asr import AsrResult, AsrSegment, register_asr
from traduko.config import BudgetConfig, CoreConfig, save_config
from traduko.events import EventBus
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.stages import base, registry


@register_asr("fake-asr")
class FakeAsr:
    last_audio_path: Path | None = None

    def __init__(self, **_params) -> None:
        pass

    def transcribe(self, audio_path, *, language=None, on_progress=None):
        FakeAsr.last_audio_path = audio_path
        if on_progress:
            on_progress(2.0, 2.0)
        return AsrResult(
            language="en",
            duration=2.0,
            segments=[
                AsrSegment(start=0.0, end=1.0, text="I went"),
                AsrSegment(start=1.1, end=2.0, text="to the store."),
            ],
        )


def make_ctx(tmp_path: Path, input_path: Path, stage_index: int = 0, params: dict | None = None):
    now = utc_now_iso()
    task = TaskRecord(
        id="t-test",
        project="default",
        input_path=str(input_path),
        profile="x",
        stages=[StageRecord(type="noop")],
        created_at=now,
        updated_at=now,
    )
    task_dir = tmp_path / "projects" / "default" / "tasks" / task.id
    progress: list[tuple[int, int]] = []
    ctx = base.StageContext(
        task=task,
        stage_index=stage_index,
        params=params or {},
        artifacts=ArtifactStore(task_dir),
        data_root=tmp_path,
        emit_progress=lambda cur, total: progress.append((cur, total)),
        should_cancel=lambda: False,
        bus=EventBus(),
    )
    return ctx, progress


def test_ingest_subtitle(tmp_path: Path) -> None:
    src = tmp_path / "in.srt"
    src.write_text("1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8")
    ctx, _ = make_ctx(tmp_path, src)
    result = registry.create("ingest_subtitle").run(ctx)
    assert result.artifacts == ["01-segments.json"]
    data = ctx.artifacts.read_latest_json("segments.json")
    assert data["segments"] == [{"id": 1, "start": 1.0, "end": 2.0, "text": "hello"}]


def test_ingest_rejects_unknown_format(tmp_path: Path) -> None:
    src = tmp_path / "in.docx"
    src.write_text("x", encoding="utf-8")
    ctx, _ = make_ctx(tmp_path, src)
    with pytest.raises(base.StageError):
        registry.create("ingest_subtitle").run(ctx)


def test_extract_audio_requires_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.av.ffmpeg_available", lambda: False)
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.mp4")
    with pytest.raises(base.StageError):
        registry.create("extract_audio").run(ctx)


def test_extract_audio_builds_and_runs_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.av.ffmpeg_available", lambda: True)
    commands: list[list[str]] = []

    def fake_run(cmd: list[str]) -> None:
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"RIFF")

    monkeypatch.setattr("traduko.stages.av.run_media", fake_run)
    ctx, progress = make_ctx(tmp_path, tmp_path / "in.mp4")
    result = registry.create("extract_audio").run(ctx)
    assert result.artifacts == ["01-audio.wav"]
    assert commands[0][0] == "ffmpeg"
    assert progress == [(1, 1)]


def test_asr_stage_uses_latest_audio_artifact(tmp_path: Path) -> None:
    ctx, progress = make_ctx(
        tmp_path, tmp_path / "in.mp4", stage_index=1, params={"provider": "fake-asr"}
    )
    audio = ctx.artifacts.path_for(1, "audio.wav")
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"RIFF")
    result = registry.create("asr").run(ctx)
    assert result.artifacts == ["02-asr.json"]
    assert FakeAsr.last_audio_path == audio
    data = ctx.artifacts.read_latest_json("asr.json")
    assert data["language"] == "en"
    assert len(data["segments"]) == 2
    assert progress[-1] == (2, 2)


def test_asr_stage_falls_back_to_input_path(tmp_path: Path) -> None:
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(tmp_path, src, params={"provider": "fake-asr"})
    registry.create("asr").run(ctx)
    assert FakeAsr.last_audio_path == src


def test_segment_stage_refines_asr(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.mp4", stage_index=2)
    ctx.artifacts.write_json(
        2,
        "asr.json",
        {
            "language": "en",
            "duration": 2.0,
            "segments": [
                {"id": 1, "start": 0.0, "end": 1.0, "text": "I went"},
                {"id": 2, "start": 1.1, "end": 2.0, "text": "to the store."},
            ],
        },
    )
    result = registry.create("segment").run(ctx)
    assert result.artifacts == ["03-segments.json"]
    data = ctx.artifacts.read_latest_json("segments.json")
    assert data["segments"] == [
        {"id": 1, "start": 0.0, "end": 2.0, "text": "I went to the store."}
    ]


def write_segments_artifact(ctx) -> None:
    ctx.artifacts.write_json(
        1,
        "segments.json",
        {
            "language": "en",
            "segments": [
                {"id": 1, "start": 0.0, "end": 1.0, "text": "hello"},
                {"id": 2, "start": 1.0, "end": 2.0, "text": "world"},
            ],
        },
    )


def test_translate_stage_happy_path(tmp_path: Path) -> None:
    ctx, progress = make_ctx(
        tmp_path,
        tmp_path / "in.srt",
        stage_index=1,
        params={"provider": "fake", "target_language": "zh-TW"},
    )
    write_segments_artifact(ctx)
    result = registry.create("translate").run(ctx)
    assert set(result.artifacts) == {"02-translation.json", "02-translation.partial.json"}
    data = ctx.artifacts.read_latest_json("translation.json")
    assert data["source_language"] == "en"
    assert data["target_language"] == "zh-TW"
    assert [s["target"] for s in data["segments"]] == ["[T] hello", "[T] world"]
    assert progress[-1] == (2, 2)


def test_translate_stage_requires_target_language(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.srt", stage_index=1, params={"provider": "fake"})
    write_segments_artifact(ctx)
    with pytest.raises(base.StageError):
        registry.create("translate").run(ctx)


def test_translate_stage_unknown_provider(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path, tmp_path / "in.srt", stage_index=1,
        params={"provider": "prod", "target_language": "zh-TW"},
    )
    write_segments_artifact(ctx)
    with pytest.raises(base.StageError):
        registry.create("translate").run(ctx)


def test_translate_stage_budget_pause(tmp_path: Path) -> None:
    save_config(tmp_path, CoreConfig(budget=BudgetConfig(task_usd_limit=0.5)))
    (tmp_path / "config" / "pricing.yaml").write_text(
        "fake-model:\n  input: 1000000.0\n  output: 1000000.0\n", encoding="utf-8"
    )
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "in.srt",
        stage_index=1,
        params={"provider": "fake", "target_language": "zh-TW", "batch_size": 1},
    )
    write_segments_artifact(ctx)
    with pytest.raises(base.PauseRequested):
        registry.create("translate").run(ctx)


def test_translate_stage_manual_pause_raises_pause_requested(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path, tmp_path / "in.srt", stage_index=1,
        params={"provider": "fake", "target_language": "zh-TW"},
    )
    write_segments_artifact(ctx)
    ctx.should_pause = lambda: True
    with pytest.raises(base.PauseRequested):
        registry.create("translate").run(ctx)


@register_asr("fake-textonly")
class FakeTextOnlyAsr:
    def __init__(self, **_params) -> None:
        pass

    def transcribe(self, audio_path, *, language=None, on_progress=None):
        return AsrResult(
            language="ja",
            duration=5.0,
            segments=[AsrSegment(start=0.0, end=0.0, text="text only", speaker="A")],
            timestamps=False,
        )


def test_asr_stage_resolves_engine_from_config(tmp_path: Path, monkeypatch) -> None:
    # No provider/engine params: the configured default engine applies and
    # its mapped options reach the provider constructor.
    captured = {}

    def fake_engine_provider(engine_id, config):
        captured["engine"] = engine_id
        return "fake-asr", {"model_size": "medium"}, True

    monkeypatch.setattr("traduko.stages.av.engine_provider", fake_engine_provider)
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(tmp_path, src)
    registry.create("asr").run(ctx)
    assert captured["engine"] == "faster_whisper"
    data = ctx.artifacts.read_latest_json("asr.json")
    assert data["timestamps"] is True


def test_asr_stage_records_missing_timestamps_and_speaker(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "traduko.stages.av.engine_provider",
        lambda engine_id, config: ("fake-textonly", {}, False),
    )
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(tmp_path, src, params={"engine": "openai_gpt4o"})
    registry.create("asr").run(ctx)
    data = ctx.artifacts.read_latest_json("asr.json")
    assert data["timestamps"] is False
    assert data["segments"][0]["speaker"] == "A"


def test_segment_stage_refuses_timestampless_asr(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.mp4", stage_index=1)
    ctx.artifacts.write_json(
        1,
        "asr.json",
        {
            "language": "ja",
            "duration": 5.0,
            "timestamps": False,
            "segments": [{"id": 1, "start": 0.0, "end": 0.0, "text": "x"}],
        },
    )
    with pytest.raises(base.StageError, match="timestamp"):
        registry.create("segment").run(ctx)


def test_segment_stage_accepts_legacy_asr_without_flag(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "in.mp4", stage_index=1)
    ctx.artifacts.write_json(
        1,
        "asr.json",
        {
            "language": "en",
            "duration": 2.0,
            "segments": [{"id": 1, "start": 0.0, "end": 1.0, "text": "hi"}],
        },
    )
    result = registry.create("segment").run(ctx)
    assert result.artifacts == ["02-segments.json"]
