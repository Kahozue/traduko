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


class CancelRequested(Exception):
    """Raised by a stage that noticed a cancel mid-run. The executor cancels
    the task; work already written stays on disk."""


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
    should_pause: Callable[[], bool] = lambda: False

    def checkpoint(self, reason: str = "manual") -> None:
        """Honour a pending cancel or pause here.

        Without this, both signals only take effect between stages, so
        cancelling a task mid-synthesis leaves it running for however long
        the stage still needs -- minutes for a real dub. Long stages call it
        once per unit of work, at a point where stopping leaves consistent
        state (a finished segment, a written partial). Cancel wins: a user
        who asked for both wants it stopped.
        """
        if self.should_cancel():
            raise CancelRequested(reason)
        if self.should_pause():
            raise PauseRequested(reason)


@dataclass
class StageResult:
    artifacts: list[str] = field(default_factory=list)
    # A stage that made its own review pointless (e.g. diarize short-circuited
    # by a non-clone voice mode) sets this to skip the profile's pause_after.
    skip_pause: bool = False


@runtime_checkable
class Stage(Protocol):
    type: str

    def run(self, ctx: StageContext) -> StageResult: ...
