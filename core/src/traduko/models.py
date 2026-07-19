"""Task and stage records. task.json on disk is the source of truth."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

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


class TaskGlossary(BaseModel):
    global_ids: list[str] = Field(default_factory=list)
    use_task: bool = False
    asr_mode: Literal["auto", "force", "off"] = "auto"


class TaskSwitches(BaseModel):
    """Pipeline switches. None means: no explicit choice, leave stages as
    the profile made them (pre-switch tasks keep behaving unchanged)."""

    translate: bool | None = None
    diarize: bool | None = None
    dub: bool | None = None


class TaskRecord(BaseModel):
    schema_version: int = 1
    id: str
    project: str
    input_path: str
    profile: str
    name: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    stages: list[StageRecord]
    glossary: TaskGlossary = Field(default_factory=TaskGlossary)
    switches: TaskSwitches | None = None
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
