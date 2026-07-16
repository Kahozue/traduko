import sqlite3
from pathlib import Path

from traduko.index import TaskIndex
from traduko.models import StageRecord, TaskStatus
from traduko.tasks import TaskStore


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


def test_index_rows_include_name(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    index = TaskIndex(tmp_path)
    record = store.create(
        project="p", input_path="/tmp/in.srt",
        profile_name="x", stages=[], name="第三集",
    )
    index.upsert(record)
    rows = index.list()
    assert rows[0]["name"] == "第三集"
    index.close()


def test_index_migrates_legacy_db_without_name_column(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "index.sqlite3")
    conn.execute(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, project TEXT NOT NULL, status TEXT NOT NULL,
            profile TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO tasks VALUES ('t1', 'p', 'completed', 'x', '2026', '2026')"
    )
    conn.commit()
    conn.close()

    index = TaskIndex(tmp_path)
    rows = index.list()
    assert rows[0]["name"] == ""
    index.close()
