import re

import pytest

from translator_core.models import (
    InvalidTransition,
    StageRecord,
    TaskRecord,
    TaskStatus,
    new_task_id,
    transition,
    utc_now_iso,
)


def make_task(status: TaskStatus = TaskStatus.PENDING) -> TaskRecord:
    now = utc_now_iso()
    return TaskRecord(
        id=new_task_id(),
        project="default",
        input_path="in.srt",
        profile="passthrough",
        status=status,
        stages=[StageRecord(type="noop")],
        created_at=now,
        updated_at=now,
    )


def test_task_id_format() -> None:
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{6}", new_task_id())


def test_legal_transition() -> None:
    task = make_task()
    transition(task, TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING
    transition(task, TaskStatus.WAITING_REVIEW)
    transition(task, TaskStatus.RUNNING)
    transition(task, TaskStatus.COMPLETED)


def test_illegal_transition_raises() -> None:
    task = make_task(TaskStatus.COMPLETED)
    with pytest.raises(InvalidTransition):
        transition(task, TaskStatus.RUNNING)


def test_failed_can_retry() -> None:
    task = make_task(TaskStatus.FAILED)
    transition(task, TaskStatus.RUNNING)
    assert task.status == TaskStatus.RUNNING
