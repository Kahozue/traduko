"""TaskStore: task.json persistence. Files are the source of truth."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text
from .models import StageRecord, TaskRecord, new_task_id, utc_now_iso

if TYPE_CHECKING:
    from .index import TaskIndex

TASK_SUBDIRS = ("artifacts", "agent-runs", "logs")


class TaskStore:
    def __init__(self, root: Path, index: "TaskIndex | None" = None) -> None:
        self.root = root
        self.index = index

    def task_dir(self, project: str, task_id: str) -> Path:
        return self.root / "projects" / project / "tasks" / task_id

    def create(
        self,
        *,
        project: str,
        input_path: str,
        profile_name: str,
        stages: list[StageRecord],
        name: str | None = None,
    ) -> TaskRecord:
        now = utc_now_iso()
        record = TaskRecord(
            id=new_task_id(),
            project=project,
            input_path=input_path,
            profile=profile_name,
            name=name or Path(input_path).stem,
            stages=stages,
            created_at=now,
            updated_at=now,
        )
        task_dir = self.task_dir(project, record.id)
        for sub in TASK_SUBDIRS:
            (task_dir / sub).mkdir(parents=True, exist_ok=True)
        self.save(record)
        return record

    def load(self, project: str, task_id: str) -> TaskRecord:
        path = self.task_dir(project, task_id) / "task.json"
        return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: TaskRecord) -> None:
        record.updated_at = utc_now_iso()
        path = self.task_dir(record.project, record.id) / "task.json"
        atomic_write_text(path, record.model_dump_json(indent=2))
        if self.index is not None:
            self.index.upsert(record)

    def iter_tasks(self, project: str | None = None) -> Iterator[TaskRecord]:
        projects_dir = self.root / "projects"
        if not projects_dir.exists():
            return
        pattern = f"{project or '*'}/tasks/*/task.json"
        for path in sorted(projects_dir.glob(pattern)):
            yield TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
