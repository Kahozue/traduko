import threading
import time
from pathlib import Path

from traduko.models import StageRecord, StageStatus, TaskRecord, TaskStatus
from traduko.service.worker import TaskWorker
from traduko.stages import registry
from traduko.stages.base import StageContext, StageResult
from traduko.workspace import Workspace


@registry.register
class GateStage:
    type = "test-gate"
    gate = threading.Event()
    started = threading.Event()

    def run(self, ctx: StageContext) -> StageResult:
        type(self).started.set()
        assert type(self).gate.wait(timeout=10)
        return StageResult()


def reset_gate() -> None:
    GateStage.gate = threading.Event()
    GateStage.started = threading.Event()


def make_task(ws: Workspace, stage_types: list[str]) -> TaskRecord:
    return ws.store.create(
        project="p",
        input_path="unused",
        profile_name="test",
        stages=[StageRecord(type=t) for t in stage_types],
    )


def wait_status(
    ws: Workspace, task_id: str, wanted: set[TaskStatus], timeout: float = 5.0
) -> TaskRecord:
    deadline = time.monotonic() + timeout
    record = ws.store.load("p", task_id)
    while time.monotonic() < deadline:
        record = ws.store.load("p", task_id)
        if record.status in wanted:
            return record
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {wanted}, last {record.status}")


def test_enqueue_runs_task_to_completion(tmp_path: Path) -> None:
    ws = Workspace.open(tmp_path)
    worker = TaskWorker(ws)
    worker.start()
    try:
        record = make_task(ws, ["noop"])
        assert worker.enqueue("p", record.id) is True
        wait_status(ws, record.id, {TaskStatus.COMPLETED})
    finally:
        worker.stop()


def test_running_task_can_be_canceled(tmp_path: Path) -> None:
    reset_gate()
    ws = Workspace.open(tmp_path)
    worker = TaskWorker(ws)
    worker.start()
    try:
        record = make_task(ws, ["test-gate", "noop"])
        worker.enqueue("p", record.id)
        assert GateStage.started.wait(timeout=5)
        assert worker.cancel("p", record.id) is True
        GateStage.gate.set()
        wait_status(ws, record.id, {TaskStatus.CANCELED})
    finally:
        GateStage.gate.set()
        worker.stop()


def test_queued_task_can_be_canceled(tmp_path: Path) -> None:
    reset_gate()
    ws = Workspace.open(tmp_path)
    worker = TaskWorker(ws)
    worker.start()
    try:
        blocker = make_task(ws, ["test-gate"])
        queued = make_task(ws, ["noop"])
        worker.enqueue("p", blocker.id)
        assert GateStage.started.wait(timeout=5)
        worker.enqueue("p", queued.id)
        assert worker.cancel("p", queued.id) is True
        GateStage.gate.set()
        wait_status(ws, blocker.id, {TaskStatus.COMPLETED})
        wait_status(ws, queued.id, {TaskStatus.CANCELED})
    finally:
        GateStage.gate.set()
        worker.stop()


def test_duplicate_enqueue_is_rejected(tmp_path: Path) -> None:
    reset_gate()
    ws = Workspace.open(tmp_path)
    worker = TaskWorker(ws)
    worker.start()
    try:
        record = make_task(ws, ["test-gate"])
        assert worker.enqueue("p", record.id) is True
        assert GateStage.started.wait(timeout=5)
        assert worker.enqueue("p", record.id) is False
        GateStage.gate.set()
        wait_status(ws, record.id, {TaskStatus.COMPLETED})
    finally:
        GateStage.gate.set()
        worker.stop()


def test_cancel_inactive_task_returns_false(tmp_path: Path) -> None:
    ws = Workspace.open(tmp_path)
    worker = TaskWorker(ws)
    assert worker.cancel("p", "missing") is False


def test_running_task_can_be_paused(tmp_path: Path) -> None:
    reset_gate()
    ws = Workspace.open(tmp_path)
    worker = TaskWorker(ws)
    worker.start()
    try:
        record = make_task(ws, ["test-gate", "noop"])
        worker.enqueue("p", record.id)
        assert GateStage.started.wait(timeout=5)
        assert worker.pause("p", record.id) is True
        GateStage.gate.set()
        paused = wait_status(ws, record.id, {TaskStatus.PAUSED})
        assert paused.stages[0].status == StageStatus.COMPLETED
        assert paused.stages[1].status == StageStatus.PENDING
    finally:
        GateStage.gate.set()
        worker.stop()


def test_pause_inactive_task_returns_false(tmp_path: Path) -> None:
    ws = Workspace.open(tmp_path)
    worker = TaskWorker(ws)
    assert worker.pause("p", "missing") is False
