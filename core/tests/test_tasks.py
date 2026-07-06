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
