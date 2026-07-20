"""Runs a task's stage sequence. Resume = call run() again."""
from __future__ import annotations

from pathlib import Path
from threading import Event as ThreadEvent

from .artifacts import ArtifactStore
from .events import Event, EventBus
from .models import StageStatus, TaskRecord, TaskStatus, transition
from .stages import base, registry
from .tasks import TaskStore


class CancelToken:
    def __init__(self) -> None:
        self._event = ThreadEvent()

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


class PauseToken(CancelToken):
    """Set-once signal asking the pipeline to pause at the next safe point."""


class PipelineExecutor:
    def __init__(self, store: TaskStore, bus: EventBus, data_root: Path) -> None:
        self.store = store
        self.bus = bus
        self.data_root = data_root

    def _emit(self, record: TaskRecord, event_type: str, data: dict) -> None:
        self.bus.publish(
            Event(type=event_type, task_id=record.id, project=record.project, data=data)
        )

    def run(
        self,
        record: TaskRecord,
        cancel: CancelToken | None = None,
        pause: PauseToken | None = None,
    ) -> TaskRecord:
        cancel = cancel or CancelToken()
        pause = pause or PauseToken()
        stage_total = len(record.stages)
        transition(record, TaskStatus.RUNNING)
        self.store.save(record)
        self._emit(record, "task_started", {"stage_total": stage_total})

        artifacts = ArtifactStore(self.store.task_dir(record.project, record.id))
        for i, stage_record in enumerate(record.stages):
            if stage_record.status == StageStatus.COMPLETED:
                continue
            if stage_record.status == StageStatus.SKIPPED:
                continue
            if cancel.is_set():
                transition(record, TaskStatus.CANCELED)
                self.store.save(record)
                self._emit(record, "task_canceled", {"stage_index": i})
                return record
            if pause.is_set():
                transition(record, TaskStatus.PAUSED)
                self.store.save(record)
                self._emit(record, "task_paused", {"stage_index": i, "reason": "manual"})
                return record

            stage_record.status = StageStatus.RUNNING
            stage_record.error = None
            self.store.save(record)
            self._emit(
                record, "stage_started", {"stage_index": i, "stage_total": stage_total}
            )
            ctx = base.StageContext(
                task=record,
                stage_index=i,
                params=stage_record.params,
                artifacts=artifacts,
                data_root=self.data_root,
                emit_progress=lambda current, total, _i=i: self._emit(
                    record,
                    "stage_progress",
                    {"stage_index": _i, "current": current, "total": total},
                ),
                should_cancel=cancel.is_set,
                bus=self.bus,
                should_pause=pause.is_set,
            )
            try:
                stage = registry.create(stage_record.type)
                result = stage.run(ctx)
            except base.CancelRequested:
                # Stopped part way through: the stage goes back to PENDING so
                # a later run redoes it rather than trusting half its output.
                stage_record.status = StageStatus.PENDING
                transition(record, TaskStatus.CANCELED)
                self.store.save(record)
                self._emit(record, "task_canceled", {"stage_index": i})
                return record
            except base.PauseRequested as paused:
                stage_record.status = StageStatus.PENDING
                transition(record, TaskStatus.PAUSED)
                self.store.save(record)
                self._emit(
                    record, "task_paused", {"stage_index": i, "reason": paused.reason}
                )
                return record
            except base.StageError as error:
                stage_record.status = StageStatus.FAILED
                stage_record.error = str(error)
                transition(record, TaskStatus.FAILED)
                self.store.save(record)
                self._emit(record, "task_failed", {"stage_index": i, "error": str(error)})
                return record

            stage_record.status = StageStatus.COMPLETED
            stage_record.artifacts = result.artifacts
            self.store.save(record)
            self._emit(
                record, "stage_completed", {"stage_index": i, "stage_total": stage_total}
            )

            remaining = any(
                s.status not in (StageStatus.COMPLETED, StageStatus.SKIPPED)
                for s in record.stages[i + 1 :]
            )
            if stage_record.pause_after and remaining and not result.skip_pause:
                transition(record, TaskStatus.WAITING_REVIEW)
                self.store.save(record)
                self._emit(record, "task_waiting_review", {"stage_index": i})
                return record

        transition(record, TaskStatus.COMPLETED)
        self.store.save(record)
        self._emit(record, "task_completed", {"stage_total": stage_total})
        return record

# Human-facing annotations, not pipeline inputs: no deliverable is derived
# from them, so editing one must not send a finished task back to pending.
ANNOTATION_ARTIFACTS = frozenset({"proofread-report.json", "qc.json"})


def reset_stages_after_artifact(record: TaskRecord, artifact_name: str) -> int:
    if artifact_name in ANNOTATION_ARTIFACTS:
        return 0
    producer = -1
    for i, stage in enumerate(record.stages):
        if any(a.endswith(f"-{artifact_name}") for a in stage.artifacts):
            producer = i
    if producer < 0:
        return 0
    reset = 0
    for stage in record.stages[producer + 1 :]:
        if stage.status != StageStatus.PENDING:
            stage.status = StageStatus.PENDING
            reset += 1
    return reset
