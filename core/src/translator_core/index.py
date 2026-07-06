"""SQLite query index. Never the source of truth: rebuildable from files."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import TaskRecord
from .tasks import TaskStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL,
    status TEXT NOT NULL,
    profile TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


class TaskIndex:
    def __init__(self, root: Path) -> None:
        self._conn = sqlite3.connect(root / "index.sqlite3")
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def upsert(self, record: TaskRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO tasks (id, project, status, profile, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at
            """,
            (
                record.id,
                record.project,
                record.status.value,
                record.profile,
                record.created_at,
                record.updated_at,
            ),
        )
        self._conn.commit()

    def list(
        self, project: str | None = None, status: str | None = None
    ) -> list[dict]:
        query = "SELECT * FROM tasks WHERE 1=1"
        args: list[str] = []
        if project is not None:
            query += " AND project = ?"
            args.append(project)
        if status is not None:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY created_at DESC"
        return [dict(row) for row in self._conn.execute(query, args)]

    def rebuild(self, store: TaskStore) -> int:
        self._conn.execute("DELETE FROM tasks")
        self._conn.commit()
        count = 0
        for record in store.iter_tasks():
            self.upsert(record)
            count += 1
        return count

    def close(self) -> None:
        self._conn.close()
