from pathlib import Path

from translator_core.index import TaskIndex
from translator_core.models import StageRecord, TaskStatus
from translator_core.tasks import TaskStore


def test_save_with_index_lists_task(tmp_path: Path) -> None:
    index = TaskIndex(tmp_path)
    store = TaskStore(tmp_path, index=index)
    record = store.create(
        project="default",
        input_path="a",
        profile_name="x",
        stages=[StageRecord(type="noop")],
    )
    rows = index.list()
    assert [row["id"] for row in rows] == [record.id]
    record.status = TaskStatus.COMPLETED
    store.save(record)
    assert index.list(status="completed")[0]["id"] == record.id
    assert index.list(status="pending") == []


def test_rebuild_from_files(tmp_path: Path) -> None:
    plain_store = TaskStore(tmp_path)
    a = plain_store.create(
        project="p1", input_path="a", profile_name="x", stages=[StageRecord(type="noop")]
    )
    index = TaskIndex(tmp_path)
    count = index.rebuild(plain_store)
    assert count == 1
    assert index.list(project="p1")[0]["id"] == a.id
