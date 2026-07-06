from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.events import EventBus
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.stages import base, registry


def make_ctx(tmp_path: Path, stage_index: int = 2, params: dict | None = None):
    now = utc_now_iso()
    task = TaskRecord(
        id="t-test",
        project="default",
        input_path=str(tmp_path / "in.mp4"),
        profile="x",
        stages=[StageRecord(type="noop")],
        created_at=now,
        updated_at=now,
    )
    task_dir = tmp_path / "projects" / "default" / "tasks" / task.id
    ctx = base.StageContext(
        task=task,
        stage_index=stage_index,
        params=params or {},
        artifacts=ArtifactStore(task_dir),
        data_root=tmp_path,
        emit_progress=lambda cur, total: None,
        should_cancel=lambda: False,
        bus=EventBus(),
    )
    return ctx


def write_translation(ctx, timed: bool = True) -> None:
    start, end = (0.0, 1.5) if timed else (None, None)
    ctx.artifacts.write_json(
        2,
        "translation.json",
        {
            "source_language": "en",
            "target_language": "zh-TW",
            "segments": [
                {"id": 1, "start": start, "end": end, "source": "hello", "target": "你好"}
            ],
        },
    )


def test_export_multiple_formats(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, params={"formats": ["srt", "vtt", "txt", "ass"]})
    write_translation(ctx)
    result = registry.create("export_subtitles").run(ctx)
    assert result.artifacts == [
        "03-subtitles.srt",
        "03-subtitles.vtt",
        "03-subtitles.txt",
        "03-subtitles.ass",
    ]
    srt = ctx.artifacts.latest_path("subtitles.srt").read_text(encoding="utf-8")
    assert "你好" in srt and "00:00:00,000 --> 00:00:01,500" in srt
    ass = ctx.artifacts.latest_path("subtitles.ass").read_text(encoding="utf-8")
    assert "[Events]" in ass and "你好" in ass


def test_export_bilingual_puts_source_below_target(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, params={"formats": ["srt"], "bilingual": True})
    write_translation(ctx)
    registry.create("export_subtitles").run(ctx)
    srt = ctx.artifacts.latest_path("subtitles.srt").read_text(encoding="utf-8")
    assert "你好\nhello" in srt


def test_export_unknown_format_raises(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, params={"formats": ["docx"]})
    write_translation(ctx)
    with pytest.raises(base.StageError):
        registry.create("export_subtitles").run(ctx)


def test_export_untimed_segments_allow_txt_only(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, params={"formats": ["txt"]})
    write_translation(ctx, timed=False)
    result = registry.create("export_subtitles").run(ctx)
    assert result.artifacts == ["03-subtitles.txt"]
    ctx2 = make_ctx(tmp_path, params={"formats": ["srt"]})
    with pytest.raises(base.StageError):
        registry.create("export_subtitles").run(ctx2)


def test_export_style_preset_from_config(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "styles.yaml").write_text(
        "big:\n  font_name: Noto Sans TC\n  font_size: 72\n", encoding="utf-8"
    )
    ctx = make_ctx(tmp_path, params={"formats": ["ass"], "style_preset": "big"})
    write_translation(ctx)
    registry.create("export_subtitles").run(ctx)
    ass = ctx.artifacts.latest_path("subtitles.ass").read_text(encoding="utf-8")
    assert "Noto Sans TC" in ass and "72" in ass


def test_export_unknown_style_preset_raises(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path, params={"formats": ["ass"], "style_preset": "nope"})
    write_translation(ctx)
    with pytest.raises(base.StageError):
        registry.create("export_subtitles").run(ctx)


def test_hardburn_requires_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.av.ffmpeg_available", lambda: False)
    ctx = make_ctx(tmp_path)
    write_translation(ctx)
    with pytest.raises(base.StageError):
        registry.create("hardburn").run(ctx)


def test_hardburn_writes_ass_and_runs_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("traduko.stages.av.ffmpeg_available", lambda: True)
    commands: list[list[str]] = []

    def fake_run(cmd: list[str]) -> None:
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"MP4")

    monkeypatch.setattr("traduko.stages.av.run_media", fake_run)
    ctx = make_ctx(tmp_path)
    write_translation(ctx)
    result = registry.create("hardburn").run(ctx)
    assert result.artifacts == ["03-burn.ass", "03-video.mp4"]
    assert ctx.artifacts.latest_path("burn.ass").exists()
    assert commands[0][0] == "ffmpeg"
    assert any("in.mp4" in part for part in commands[0])
