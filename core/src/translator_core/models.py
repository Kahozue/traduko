"""Task and stage records. task.json on disk is the source of truth."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_REVIEW = "waiting_review"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageRecord(BaseModel):
    type: str
    status: StageStatus = StageStatus.PENDING
    params: dict = Field(default_factory=dict)
    pause_after: bool = False
    artifacts: list[str] = Field(default_factory=list)
    error: str | None = None


class TaskRecord(BaseModel):
    schema_version: int = 1
    id: str
    project: str
    input_path: str
    profile: str
    status: TaskStatus = TaskStatus.PENDING
    stages: list[StageRecord]
    created_at: str
    updated_at: str


class InvalidTransition(Exception):
    pass


_ALLOWED: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELED},
    TaskStatus.RUNNING: {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELED,
        TaskStatus.WAITING_REVIEW,
        TaskStatus.PAUSED,
    },
    TaskStatus.WAITING_REVIEW: {TaskStatus.RUNNING, TaskStatus.CANCELED},
    TaskStatus.PAUSED: {TaskStatus.RUNNING, TaskStatus.CANCELED},
    TaskStatus.FAILED: {TaskStatus.RUNNING},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELED: set(),
}


def transition(record: TaskRecord, new: TaskStatus) -> None:
    if new not in _ALLOWED[record.status]:
        raise InvalidTransition(f"{record.status.value} -> {new.value}")
    record.status = new


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_task_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"
