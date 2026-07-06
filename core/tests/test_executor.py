from pathlib import Path

import pytest

from traduko.events import Event, EventBus
from traduko.executor import CancelToken, PipelineExecutor
from traduko.models import StageStatus, TaskStatus
from traduko.profiles import Profile, ProfileStage, stage_records_from
from traduko.stages import base, registry
from traduko.tasks import TaskStore


@registry.register
class MarkStage:
    type = "mark"

    def run(self, ctx: base.StageContext) -> base.StageResult:
        ctx.emit_progress(1, 1)
        path = ctx.artifacts.write_json(
            ctx.stage_index + 1, "mark.json", {"stage_index": ctx.stage_index}
        )
        return base.StageResult(artifacts=[path.name])


@registry.register
class BoomStage:
    type = "boom"

    def run(self, ctx: base.StageContext) -> base.StageResult:
        raise base.StageError("boom")


def build(tmp_path: Path, stage_types: list[ProfileStage]):
    store = TaskStore(tmp_path)
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(events.append)
    profile = Profile(name="test", stages=stage_types)
    record = store.create(
        project="default",
        input_path="in",
        profile_name="test",
        stages=stage_records_from(profile),
    )
    return store, bus, events, record


def test_happy_path_completes_with_artifacts_and_events(tmp_path: Path) -> None:
    store, bus, events, record = build(
        tmp_path, [ProfileStage(type="mark"), ProfileStage(type="mark")]
    )
    result = PipelineExecutor(store, bus, tmp_path).run(record)
    assert result.status == TaskStatus.COMPLETED
    assert [s.status for s in result.stages] == [StageStatus.COMPLETED] * 2
    assert result.stages[0].artifacts == ["01-mark.json"]
    assert [e.type for e in events] == [
        "task_started",
        "stage_started",
        "stage_progress",
        "stage_completed",
        "stage_started",
        "stage_progress",
        "stage_completed",
        "task_completed",
    ]


def test_failure_marks_task_failed_and_rerun_retries(tmp_path: Path) -> None:
    store, bus, events, record = build(
        tmp_path, [ProfileStage(type="mark"), ProfileStage(type="boom")]
    )
    executor = PipelineExecutor(store, bus, tmp_path)
    result = executor.run(record)
    assert result.status == TaskStatus.FAILED
    assert result.stages[1].status == StageStatus.FAILED
    assert result.stages[1].error == "boom"
    rerun = executor.run(result)
    assert rerun.status == TaskStatus.FAILED
    assert rerun.stages[0].status == StageStatus.COMPLETED


def test_pause_after_creates_checkpoint_then_resumes(tmp_path: Path) -> None:
    store, bus, events, record = build(
        tmp_path,
        [ProfileStage(type="mark", pause_after=True), ProfileStage(type="mark")],
    )
    executor = PipelineExecutor(store, bus, tmp_path)
    paused = executor.run(record)
    assert paused.status == TaskStatus.WAITING_REVIEW
    assert paused.stages[1].status == StageStatus.PENDING
    resumed = executor.run(paused)
    assert resumed.status == TaskStatus.COMPLETED


def test_cancel_before_stage(tmp_path: Path) -> None:
    store, bus, events, record = build(tmp_path, [ProfileStage(type="mark")])
    cancel = CancelToken()
    cancel.set()
    result = PipelineExecutor(store, bus, tmp_path).run(record, cancel=cancel)
    assert result.status == TaskStatus.CANCELED
    assert result.stages[0].status == StageStatus.PENDING


def test_unknown_stage_type_fails_task(tmp_path: Path) -> None:
    store, bus, events, record = build(tmp_path, [ProfileStage(type="nope")])
    result = PipelineExecutor(store, bus, tmp_path).run(record)
    assert result.status == TaskStatus.FAILED
    assert "nope" in (result.stages[0].error or "")


def test_profile_yaml_roundtrip(tmp_path: Path) -> None:
    from traduko.profiles import load_profile, save_profile

    profile = Profile(name="p", stages=[ProfileStage(type="noop", pause_after=True)])
    save_profile(tmp_path, profile)
    loaded = load_profile(tmp_path, "p")
    assert loaded == profile


def test_pause_requested_pauses_task_then_resumes(tmp_path: Path) -> None:
    @registry.register
    class PauseOnceStage:
        type = "pause_once"
        seen: set[str] = set()

        def run(self, ctx: base.StageContext) -> base.StageResult:
            if ctx.task.id not in PauseOnceStage.seen:
                PauseOnceStage.seen.add(ctx.task.id)
                raise base.PauseRequested("budget exhausted")
            return base.StageResult()

    store, bus, events, record = build(tmp_path, [ProfileStage(type="pause_once")])
    executor = PipelineExecutor(store, bus, tmp_path)
    paused = executor.run(record)
    assert paused.status == TaskStatus.PAUSED
    assert paused.stages[0].status == StageStatus.PENDING
    assert events[-1].type == "task_paused"
    assert events[-1].data["reason"] == "budget exhausted"
    resumed = executor.run(paused)
    assert resumed.status == TaskStatus.COMPLETED


def test_stage_context_carries_bus(tmp_path: Path) -> None:
    @registry.register
    class BusProbeStage:
        type = "bus_probe"

        def run(self, ctx: base.StageContext) -> base.StageResult:
            assert ctx.bus is not None
            return base.StageResult()

    store, bus, events, record = build(tmp_path, [ProfileStage(type="bus_probe")])
    result = PipelineExecutor(store, bus, tmp_path).run(record)
    assert result.status == TaskStatus.COMPLETED
