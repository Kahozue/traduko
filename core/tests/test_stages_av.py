import json
from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.asr import AsrResult, AsrSegment, register_asr
from traduko.config import BudgetConfig, CoreConfig, save_config
from traduko.events import EventBus
from traduko.glossary import GlossaryEntry, GlossaryStore
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.stages import base, registry


@register_asr("fake-asr")
class FakeAsr:
    last_audio_path: Path | None = None
    last_glossary_terms: list[str] | None = None

    def __init__(self, **_params) -> None:
        pass

    def transcribe(
        self,
        audio_path,
        *,
        language=None,
        on_progress=None,
        glossary_terms=None,
    ):
        FakeAsr.last_audio_path = audio_path
        FakeAsr.last_glossary_terms = glossary_terms
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


def test_ingest_transcript_from_srt_file_keeps_timestamps(tmp_path: Path) -> None:
    src = tmp_path / "transcript.srt"
    src.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nhello\n\n"
        "2\n00:00:03,000 --> 00:00:04,500\nthere\n",
        encoding="utf-8",
    )
    ctx, progress = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "file", "path": str(src)}},
    )

    result = registry.create("ingest_transcript").run(ctx)

    assert result.artifacts == ["01-segments.json"]
    data = ctx.artifacts.read_latest_json("segments.json")
    assert data["timestamps"] is True
    assert data["segments"] == [
        {"id": 1, "start": 1.0, "end": 2.0, "text": "hello"},
        {"id": 2, "start": 3.0, "end": 4.5, "text": "there"},
    ]
    assert progress == [(1, 1)]


def test_ingest_transcript_from_txt_file_has_no_timestamps(tmp_path: Path) -> None:
    src = tmp_path / "transcript.txt"
    src.write_text("first line\nsecond line\n", encoding="utf-8")
    ctx, _ = make_ctx(
        tmp_path,
        src,
        params={"transcript": {"kind": "file", "path": str(src)}},
    )

    registry.create("ingest_transcript").run(ctx)

    data = ctx.artifacts.read_latest_json("segments.json")
    assert data["timestamps"] is False
    assert data["segments"] == [
        {"id": 1, "start": None, "end": None, "text": "first line"},
        {"id": 2, "start": None, "end": None, "text": "second line"},
    ]


def test_ingest_transcript_from_task_artifact(tmp_path: Path) -> None:
    artifact = (
        tmp_path / "projects" / "default" / "tasks" / "t-src" / "artifacts"
        / "06-subtitles.srt"
    )
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(
        "1\n00:00:00,500 --> 00:00:01,500\nfrom task\n", encoding="utf-8"
    )
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={
            "transcript": {
                "kind": "task",
                "project": "default",
                "task_id": "t-src",
                "file": "06-subtitles.srt",
            }
        },
    )

    registry.create("ingest_transcript").run(ctx)

    data = ctx.artifacts.read_latest_json("segments.json")
    assert data["timestamps"] is True
    assert data["segments"] == [
        {"id": 1, "start": 0.5, "end": 1.5, "text": "from task"}
    ]


def test_ingest_transcript_missing_file_names_the_source(tmp_path: Path) -> None:
    missing = tmp_path / "gone.srt"
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "file", "path": str(missing)}},
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    message = str(error.value)
    assert "gone.srt" in message
    assert "file" in message


def test_ingest_transcript_missing_task_artifact_names_the_source(
    tmp_path: Path,
) -> None:
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={
            "transcript": {
                "kind": "task",
                "project": "default",
                "task_id": "t-src",
                "file": "06-subtitles.srt",
            }
        },
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    message = str(error.value)
    assert "task artifact" in message
    assert "t-src" in message


def test_ingest_transcript_reads_translation_json_targets(tmp_path: Path) -> None:
    # spec section 7 offers translation.json as a compose source; its target
    # text is what should be voiced.
    src = tmp_path / "05-translation.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "language": "ja",
                "target_language": "zh-TW",
                "segments": [
                    {"id": 1, "start": 1.0, "end": 2.0, "source": "おはよう", "target": "早安"},
                    {"id": 2, "start": 3.0, "end": 4.5, "source": "またね", "target": "再見"},
                ],
            }
        ),
        encoding="utf-8",
    )
    ctx, progress = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "file", "path": str(src)}},
    )

    result = registry.create("ingest_transcript").run(ctx)

    assert result.artifacts == ["01-segments.json"]
    data = ctx.artifacts.read_latest_json("segments.json")
    assert data["timestamps"] is True
    assert data["segments"] == [
        {"id": 1, "start": 1.0, "end": 2.0, "text": "早安"},
        {"id": 2, "start": 3.0, "end": 4.5, "text": "再見"},
    ]
    assert progress == [(1, 1)]


def test_ingest_transcript_translation_json_falls_back_to_source_text(
    tmp_path: Path,
) -> None:
    src = tmp_path / "translation.json"
    src.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "segments": [
                    {"id": 1, "start": 0.0, "end": 1.0, "source": "hello", "target": ""},
                ],
            }
        ),
        encoding="utf-8",
    )
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "file", "path": str(src)}},
    )

    registry.create("ingest_transcript").run(ctx)

    data = ctx.artifacts.read_latest_json("segments.json")
    assert data["segments"][0]["text"] == "hello"


def test_ingest_transcript_rejects_a_json_without_segments(tmp_path: Path) -> None:
    src = tmp_path / "notes.json"
    src.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "file", "path": str(src)}},
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "segments" in str(error.value)


def test_ingest_transcript_rejects_unsupported_format(tmp_path: Path) -> None:
    src = tmp_path / "transcript.docx"
    src.write_text("x", encoding="utf-8")
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "file", "path": str(src)}},
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "transcript.docx" in str(error.value)


def test_ingest_transcript_rejects_empty_transcript(tmp_path: Path) -> None:
    src = tmp_path / "transcript.txt"
    src.write_text("\n  \n", encoding="utf-8")
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "file", "path": str(src)}},
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "no transcript lines" in str(error.value)


def test_ingest_transcript_requires_the_transcript_param(tmp_path: Path) -> None:
    ctx, _ = make_ctx(tmp_path, tmp_path / "movie.mp4")

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "params.transcript" in str(error.value)


def test_ingest_transcript_rejects_unknown_source_kind(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "url", "path": "http://example.com/a.srt"}},
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "transcript.kind" in str(error.value)


def test_ingest_transcript_file_source_requires_a_path(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path, tmp_path / "movie.mp4", params={"transcript": {"kind": "file"}}
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "transcript.path" in str(error.value)


def test_ingest_transcript_task_source_requires_all_fields(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={"transcript": {"kind": "task", "project": "default"}},
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "transcript.task_id" in str(error.value)


def test_ingest_transcript_task_source_rejects_nested_file(tmp_path: Path) -> None:
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "movie.mp4",
        params={
            "transcript": {
                "kind": "task",
                "project": "default",
                "task_id": "t-src",
                "file": "../../task.json",
            }
        },
    )

    with pytest.raises(base.StageError) as error:
        registry.create("ingest_transcript").run(ctx)

    assert "transcript.file" in str(error.value)


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


def test_asr_stage_passes_deduped_glossary_terms_to_capable_engine(
    tmp_path: Path, monkeypatch
) -> None:
    store = GlossaryStore(tmp_path)
    first = store.create_table("First", "video")
    second = store.create_table("Second", "general")
    store.write_entries(
        first.id,
        [
            GlossaryEntry(source=f"Term {index}", target=f"譯名 {index}")
            for index in range(100)
        ]
        + [GlossaryEntry(source="Duplicate", target="第一")],
    )
    store.write_entries(
        second.id,
        [
            GlossaryEntry(source="Duplicate", target="第二"),
            GlossaryEntry(source="Over limit", target="超限"),
        ],
    )
    monkeypatch.setattr(
        "traduko.stages.av.engine_provider",
        lambda engine_id, config: ("fake-asr", {}, True),
    )
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(tmp_path, src, params={"engine": "faster_whisper"})

    registry.create("asr").run(ctx)

    assert FakeAsr.last_glossary_terms == [f"Term {index}" for index in range(100)]


def test_asr_stage_biases_legacy_faster_whisper_profile(
    tmp_path: Path, monkeypatch
) -> None:
    store = GlossaryStore(tmp_path)
    table = store.create_table("Terms", "video")
    store.write_entries(table.id, [GlossaryEntry(source="Traduko", target="譯者")])
    monkeypatch.setattr(
        "traduko.stages.av.create_asr", lambda provider_name, **options: FakeAsr()
    )
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(tmp_path, src, params={"provider": "faster_whisper"})

    registry.create("asr").run(ctx)

    assert FakeAsr.last_glossary_terms == ["Traduko"]


@pytest.mark.parametrize(
    ("engine", "asr_mode"),
    [("cloud_custom", "auto"), ("faster_whisper", "off")],
)
def test_asr_stage_omits_glossary_terms_when_bias_is_unavailable_or_disabled(
    tmp_path: Path, monkeypatch, engine: str, asr_mode: str
) -> None:
    store = GlossaryStore(tmp_path)
    table = store.create_table("Terms", "video")
    store.write_entries(table.id, [GlossaryEntry(source="Traduko", target="譯者")])
    monkeypatch.setattr(
        "traduko.stages.av.engine_provider",
        lambda engine_id, config: ("fake-asr", {}, True),
    )
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(tmp_path, src, params={"engine": engine})
    ctx.task.glossary.asr_mode = asr_mode

    registry.create("asr").run(ctx)

    assert FakeAsr.last_glossary_terms is None


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


# --- cloud ASR spend lands on the budget ledger (v3-10) ---


def test_asr_stage_records_cloud_spend(tmp_path: Path, monkeypatch) -> None:
    import json

    save_config(tmp_path, CoreConfig())
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(
        tmp_path, src, stage_index=1, params={"engine": "openai_whisper"}
    )
    captured: dict = {}

    def fake_create(name, **options):
        captured["name"] = name
        captured["options"] = options
        return FakeAsr()

    monkeypatch.setattr("traduko.stages.av.create_asr", fake_create)
    registry.create("asr").run(ctx)
    assert captured["name"] == "openai_cloud"
    ledger_files = list((tmp_path / "budget").glob("ledger-*.jsonl"))
    assert len(ledger_files) == 1
    row = json.loads(ledger_files[0].read_text(encoding="utf-8").splitlines()[0])
    assert row["kind"] == "asr"
    assert row["model"] == "whisper-1"
    assert row["seconds"] == 2.0
    assert row["cost_usd"] == pytest.approx(2.0 / 60 * 0.006)
    assert row["price_known"] is True
    assert row["task_id"] == "t-test"


def test_asr_stage_local_engine_stays_off_the_ledger(tmp_path: Path) -> None:
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(tmp_path, src, params={"provider": "fake-asr"})
    registry.create("asr").run(ctx)
    assert not (tmp_path / "budget").exists()


def test_asr_stage_pauses_when_budget_is_spent(tmp_path: Path, monkeypatch) -> None:
    from traduko.budget import BudgetMeter
    from traduko.events import EventBus as Bus

    config = CoreConfig(budget=BudgetConfig(monthly_usd_limit=1.0))
    save_config(tmp_path, config)
    # Pre-spend past the monthly cap: 12000s at 0.006/min = 1.2 USD.
    BudgetMeter(tmp_path, Bus(), config).record_asr(
        "whisper-1", 12000.0, project="default", task_id="warmup"
    )
    src = tmp_path / "in.wav"
    src.write_bytes(b"RIFF")
    ctx, _ = make_ctx(
        tmp_path, src, stage_index=1, params={"engine": "openai_whisper"}
    )
    monkeypatch.setattr(
        "traduko.stages.av.create_asr",
        lambda name, **options: pytest.fail("must not transcribe past the cap"),
    )
    with pytest.raises(base.PauseRequested, match="budget"):
        registry.create("asr").run(ctx)


def _write_translate_template_override(tmp_path: Path, body: str) -> None:
    directory = tmp_path / "prompts"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "translate.txt").write_text(body, encoding="utf-8")


def test_translate_stage_prompt_override_bypasses_template_file(
    tmp_path: Path,
) -> None:
    # A template file that can never render: reaching for it would fail.
    _write_translate_template_override(tmp_path, "${no_such_variable}")
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "in.srt",
        stage_index=1,
        params={
            "provider": "fake",
            "target_language": "zh-TW",
            "prompt_override": "Translate to ${target_language}: ${segments_json}",
        },
    )
    write_segments_artifact(ctx)

    result = registry.create("translate").run(ctx)

    assert "02-translation.json" in result.artifacts


def test_translate_stage_prompt_override_missing_variable_names_the_override(
    tmp_path: Path,
) -> None:
    ctx, _ = make_ctx(
        tmp_path,
        tmp_path / "in.srt",
        stage_index=1,
        params={
            "provider": "fake",
            "target_language": "zh-TW",
            "prompt_override": "${no_such_variable}",
        },
    )
    write_segments_artifact(ctx)

    with pytest.raises(base.StageError) as error:
        registry.create("translate").run(ctx)

    assert "prompt override" in str(error.value).lower()
