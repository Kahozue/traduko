from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..artifacts import ArtifactStore
from ..events import EventBus
from ..models import TaskRecord


class StageError(Exception):
    pass


class UnknownStageError(StageError):
    pass


class PauseRequested(Exception):
    """Raised by a stage to pause the task without failing it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class StageContext:
    task: TaskRecord
    stage_index: int
    params: dict
    artifacts: ArtifactStore
    data_root: Path
    emit_progress: Callable[[int, int], None]
    should_cancel: Callable[[], bool]
    bus: EventBus


@dataclass
class StageResult:
    artifacts: list[str] = field(default_factory=list)


@runtime_checkable
class Stage(Protocol):
    type: str

    def run(self, ctx: StageContext) -> StageResult: ...
