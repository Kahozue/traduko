import json
from pathlib import Path

from traduko.models import StageRecord, TaskStatus
from traduko.tasks import TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(tmp_path)


def test_create_writes_readable_layout(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    record = store.create(
        project="default",
        input_path="in.srt",
        profile_name="passthrough",
        stages=[StageRecord(type="noop")],
    )
    task_dir = tmp_path / "projects" / "default" / "tasks" / record.id
    assert (task_dir / "task.json").exists()
    for sub in ("artifacts", "agent-runs", "logs"):
        assert (task_dir / sub).is_dir()
    data = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["status"] == "pending"


def test_load_save_roundtrip_bumps_updated_at(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    record = store.create(
        project="default",
        input_path="in.srt",
        profile_name="passthrough",
        stages=[StageRecord(type="noop")],
    )
    record.status = TaskStatus.RUNNING
    before = record.updated_at
    store.save(record)
    loaded = store.load("default", record.id)
    assert loaded.status == TaskStatus.RUNNING
    assert loaded.updated_at >= before


def test_iter_tasks(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    a = store.create(
        project="p1", input_path="a", profile_name="x", stages=[StageRecord(type="noop")]
    )
    store.create(
        project="p2", input_path="b", profile_name="x", stages=[StageRecord(type="noop")]
    )
    all_ids = {t.id for t in store.iter_tasks()}
    assert len(all_ids) == 2
    p1_ids = {t.id for t in store.iter_tasks("p1")}
    assert p1_ids == {a.id}


def test_create_defaults_name_to_input_stem(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    record = store.create(
        project="p", input_path="/tmp/movie final.srt",
        profile_name="x", stages=[],
    )
    assert record.name == "movie final"


def test_create_accepts_explicit_name(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    record = store.create(
        project="p", input_path="/tmp/in.srt",
        profile_name="x", stages=[], name="第三集",
    )
    assert record.name == "第三集"
    reloaded = store.load("p", record.id)
    assert reloaded.name == "第三集"


def _llm_stages() -> list[StageRecord]:
    return [
        StageRecord(type="ingest_subtitle"),
        StageRecord(type="translate", params={"provider": "fake", "target_language": "en"}),
        StageRecord(type="proofread", params={"provider": "fake"}),
        StageRecord(type="glossary_proofread"),
    ]


def test_apply_model_override_sets_llm_stage_params() -> None:
    from traduko.models import TaskRecord, utc_now_iso
    from traduko.tasks import apply_model_override

    now = utc_now_iso()
    task = TaskRecord(
        id="t", project="p", input_path="in.srt", profile="x",
        stages=_llm_stages(), created_at=now, updated_at=now,
    )
    apply_model_override(task, provider="deepseek", model="deepseek-chat")
    assert task.stages[0].params == {}
    assert task.stages[1].params["provider"] == "deepseek"
    assert task.stages[1].params["model"] == "deepseek-chat"
    assert task.stages[2].params["provider"] == "deepseek"
    assert task.stages[2].params["model"] == "deepseek-chat"
    assert task.stages[3].params["provider"] == "deepseek"
    assert task.stages[3].params["model"] == "deepseek-chat"
    # Untouched params survive.
    assert task.stages[1].params["target_language"] == "en"


def test_apply_model_override_empty_strings_reset() -> None:
    from traduko.models import TaskRecord, utc_now_iso
    from traduko.tasks import apply_model_override

    now = utc_now_iso()
    task = TaskRecord(
        id="t", project="p", input_path="in.srt", profile="x",
        stages=_llm_stages(), created_at=now, updated_at=now,
    )
    apply_model_override(task, provider="deepseek", model="deepseek-chat")
    apply_model_override(task, provider="", model="")
    assert task.stages[1].params["provider"] == "fake"
    assert "model" not in task.stages[1].params
    assert task.stages[2].params["provider"] == "fake"
    assert task.stages[3].params["provider"] == "fake"


def test_apply_model_override_none_leaves_untouched() -> None:
    from traduko.models import TaskRecord, utc_now_iso
    from traduko.tasks import apply_model_override

    now = utc_now_iso()
    task = TaskRecord(
        id="t", project="p", input_path="in.srt", profile="x",
        stages=_llm_stages(), created_at=now, updated_at=now,
    )
    apply_model_override(task, provider="deepseek", model=None)
    assert task.stages[1].params["provider"] == "deepseek"
    assert "model" not in task.stages[1].params
    apply_model_override(task, provider=None, model="glm-4")
    assert task.stages[1].params["provider"] == "deepseek"
    assert task.stages[1].params["model"] == "glm-4"


def test_force_mode_inserts_glossary_proofread_after_capable_asr() -> None:
    from traduko.config import CoreConfig
    from traduko.models import TaskGlossary, TaskRecord, utc_now_iso
    from traduko.tasks import ensure_glossary_proofread_stage

    now = utc_now_iso()
    task = TaskRecord(
        id="t",
        project="p",
        input_path="in.wav",
        profile="x",
        glossary=TaskGlossary(asr_mode="force"),
        stages=[
            StageRecord(type="extract_audio"),
            StageRecord(type="asr", params={"engine": "faster_whisper"}),
            StageRecord(type="segment"),
        ],
        created_at=now,
        updated_at=now,
    )

    ensure_glossary_proofread_stage(task, CoreConfig())

    assert [stage.type for stage in task.stages] == [
        "extract_audio",
        "asr",
        "glossary_proofread",
        "segment",
    ]


def _dub_stages():
    from traduko.models import StageRecord

    return [
        StageRecord(type="translate", params={"provider": "fake"}),
        StageRecord(type="diarize", pause_after=True),
        StageRecord(type="tts_synthesize"),
        StageRecord(type="align_duration"),
        StageRecord(type="mix_audio"),
    ]


def test_apply_voice_mode_override_targets_dub_stages() -> None:
    from traduko.models import TaskRecord, utc_now_iso
    from traduko.tasks import apply_voice_mode_override

    now = utc_now_iso()
    task = TaskRecord(
        id="t", project="p", input_path="in.mp4", profile="x",
        stages=_dub_stages(), created_at=now, updated_at=now,
    )
    apply_voice_mode_override(task, "preview", None)
    by_type = {s.type: s for s in task.stages}
    for stage_type in ("diarize", "tts_synthesize", "align_duration"):
        assert by_type[stage_type].params["voice_mode"] == "preview"
    assert "voice_mode" not in by_type["mix_audio"].params
    assert "voice_mode" not in by_type["translate"].params

    apply_voice_mode_override(task, "design", "沉穩男聲")
    assert by_type["tts_synthesize"].params["voice_instruction"] == "沉穩男聲"
    assert by_type["align_duration"].params["voice_instruction"] == "沉穩男聲"
    assert "voice_instruction" not in by_type["diarize"].params

    # "clone" and "" both mean: back to the default, no override params.
    apply_voice_mode_override(task, "clone", "")
    for stage_type in ("diarize", "tts_synthesize", "align_duration"):
        assert "voice_mode" not in by_type[stage_type].params
        assert "voice_instruction" not in by_type[stage_type].params

    # None leaves everything untouched.
    apply_voice_mode_override(task, "design", None)
    apply_voice_mode_override(task, None, None)
    assert by_type["tts_synthesize"].params["voice_mode"] == "design"


def test_reset_for_rerun_resets_all_stages_and_status(tmp_path: Path) -> None:
    from traduko.models import StageStatus

    store = make_store(tmp_path)
    record = store.create(
        project="default",
        input_path="in.srt",
        profile_name="passthrough",
        stages=[StageRecord(type="a"), StageRecord(type="b")],
    )
    record.status = TaskStatus.COMPLETED
    record.stages[0].status = StageStatus.COMPLETED
    record.stages[0].artifacts = ["0001-out.json"]
    record.stages[1].status = StageStatus.FAILED
    record.stages[1].error = "boom"
    store.save(record)

    store.reset_for_rerun(record)

    assert record.status == TaskStatus.PENDING
    for stage in record.stages:
        assert stage.status == StageStatus.PENDING
        assert stage.error is None
    # Products stay on disk; the executor overwrites each artifact on rerun.
    assert record.stages[0].artifacts == ["0001-out.json"]
    reloaded = store.load("default", record.id)
    assert reloaded.status == TaskStatus.PENDING
    assert all(s.status == StageStatus.PENDING for s in reloaded.stages)
    assert all(s.error is None for s in reloaded.stages)


def test_reset_for_rerun_rejects_non_completed(tmp_path: Path) -> None:
    import pytest

    store = make_store(tmp_path)
    record = store.create(
        project="default",
        input_path="in.srt",
        profile_name="passthrough",
        stages=[StageRecord(type="a")],
    )
    assert record.status == TaskStatus.PENDING
    with pytest.raises(ValueError):
        store.reset_for_rerun(record)
