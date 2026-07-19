"""export_video / export_audio_custom stages (export studio)."""
from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.events import EventBus
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.stages import base, registry


def make_ctx(tmp_path: Path, stage_index: int = 4, params: dict | None = None):
    now = utc_now_iso()
    source = tmp_path / "in.mp4"
    source.write_bytes(b"not really a video")
    task = TaskRecord(
        id="t-export",
        project="default",
        input_path=str(source),
        profile="x",
        stages=[StageRecord(type="noop")],
        created_at=now,
        updated_at=now,
    )
    task_dir = tmp_path / "projects" / "default" / "tasks" / task.id
    artifacts = ArtifactStore(task_dir)
    artifacts.dir.mkdir(parents=True, exist_ok=True)
    return base.StageContext(
        task=task,
        stage_index=stage_index,
        params=params or {},
        artifacts=artifacts,
        data_root=tmp_path,
        emit_progress=lambda cur, total: None,
        should_cancel=lambda: False,
        bus=EventBus(),
    )


def write_translation(ctx) -> None:
    ctx.artifacts.write_json(
        2,
        "translation.json",
        {
            "source_language": "en",
            "target_language": "zh-TW",
            "segments": [
                {"id": 1, "start": 0.0, "end": 1.5, "source": "hello", "target": "你好"}
            ],
        },
    )


@pytest.fixture
def captured_cmds(monkeypatch):
    cmds: list[list[str]] = []

    def fake_run(cmd):
        cmds.append(cmd)
        Path(cmd[-1]).write_bytes(b"encoded")

    monkeypatch.setattr("traduko.stages.export.ffmpeg_available", lambda: True)
    monkeypatch.setattr("traduko.stages.export.run_media", fake_run)
    return cmds


def test_export_video_writes_numbered_artifact(tmp_path: Path, captured_cmds) -> None:
    ctx = make_ctx(tmp_path, params={"container": "mp4", "crf": 22})
    result = registry.create("export_video").run(ctx)
    assert result.artifacts == ["05-export-1.mp4"]
    assert (ctx.artifacts.dir / "05-export-1.mp4").exists()
    cmd = captured_cmds[0]
    assert cmd[cmd.index("-crf") + 1] == "22"


def test_export_video_second_export_gets_next_sequence(
    tmp_path: Path, captured_cmds
) -> None:
    registry.create("export_video").run(make_ctx(tmp_path, stage_index=4))
    second = make_ctx(tmp_path, stage_index=5, params={"container": "mkv"})
    result = registry.create("export_video").run(second)
    assert result.artifacts == ["06-export-2.mkv"]
    assert (second.artifacts.dir / "05-export-1.mp4").exists()


def test_export_video_burns_subtitles_from_translation(
    tmp_path: Path, captured_cmds
) -> None:
    ctx = make_ctx(tmp_path, params={"subtitles": "target"})
    write_translation(ctx)
    result = registry.create("export_video").run(ctx)
    assert result.artifacts == ["05-export-1.ass", "05-export-1.mp4"]
    body = (ctx.artifacts.dir / "05-export-1.ass").read_text(encoding="utf-8")
    assert "你好" in body
    vf = captured_cmds[-1][captured_cmds[-1].index("-vf") + 1]
    assert vf.startswith("ass=")


def test_export_video_bilingual_subtitles_include_source(
    tmp_path: Path, captured_cmds
) -> None:
    ctx = make_ctx(tmp_path, params={"subtitles": "bilingual"})
    write_translation(ctx)
    registry.create("export_video").run(ctx)
    body = (ctx.artifacts.dir / "05-export-1.ass").read_text(encoding="utf-8")
    assert "你好" in body and "hello" in body


def test_export_video_subtitles_without_translation_raises(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, params={"subtitles": "target"})
    with pytest.raises(base.StageError):
        registry.create("export_video").run(ctx)


def test_export_video_dub_track_needs_dub_mix(tmp_path: Path, captured_cmds) -> None:
    ctx = make_ctx(tmp_path, params={"audio_track": "dub"})
    with pytest.raises(base.StageError):
        registry.create("export_video").run(ctx)
    ctx.artifacts.path_for(3, "dub-mix.wav").write_bytes(b"mix")
    ctx2 = make_ctx(tmp_path, params={"audio_track": "dub"})
    registry.create("export_video").run(ctx2)
    assert captured_cmds[-1].count("-i") == 2


def test_export_video_requires_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.export.ffmpeg_available", lambda: False)
    with pytest.raises(base.StageError):
        registry.create("export_video").run(make_ctx(tmp_path))


def test_export_video_rejects_unknown_container(tmp_path: Path, captured_cmds) -> None:
    ctx = make_ctx(tmp_path, params={"container": "avi"})
    with pytest.raises(base.StageError):
        registry.create("export_video").run(ctx)


def test_export_audio_custom_encodes_requested_format(
    tmp_path: Path, captured_cmds
) -> None:
    ctx = make_ctx(
        tmp_path,
        params={"format": "mp3", "source": "original", "bitrate_kbps": 160},
    )
    result = registry.create("export_audio_custom").run(ctx)
    assert result.artifacts == ["05-export-1.mp3"]
    cmd = captured_cmds[0]
    assert cmd[cmd.index("-c:a") + 1] == "libmp3lame"
    assert cmd[cmd.index("-b:a") + 1] == "160k"
    assert cmd[cmd.index("-i") + 1] == ctx.task.input_path


def test_export_audio_custom_dub_source_reads_mix(
    tmp_path: Path, captured_cmds
) -> None:
    ctx = make_ctx(tmp_path, params={"format": "wav", "source": "dub"})
    with pytest.raises(base.StageError):
        registry.create("export_audio_custom").run(ctx)
    mix = ctx.artifacts.path_for(3, "dub-mix.wav")
    mix.write_bytes(b"mix")
    ctx2 = make_ctx(tmp_path, params={"format": "wav", "source": "dub"})
    registry.create("export_audio_custom").run(ctx2)
    assert captured_cmds[-1][captured_cmds[-1].index("-i") + 1] == str(mix)


def test_export_audio_custom_rejects_unknown_format(tmp_path: Path, captured_cmds) -> None:
    ctx = make_ctx(tmp_path, params={"format": "aiff"})
    with pytest.raises(base.StageError):
        registry.create("export_audio_custom").run(ctx)


def test_export_audio_custom_requires_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.export.ffmpeg_available", lambda: False)
    with pytest.raises(base.StageError):
        registry.create("export_audio_custom").run(make_ctx(tmp_path))
