import json
from pathlib import Path

from traduko.eventlog import EventLogger
from traduko.events import Event, EventBus


def make_event(event_type: str, data: dict | None = None) -> Event:
    return Event(type=event_type, task_id="t1", project="p", data=data or {})


def log_path(tmp_path: Path) -> Path:
    return tmp_path / "projects" / "p" / "tasks" / "t1" / "logs" / "events.jsonl"


def test_appends_jsonl_per_event(tmp_path: Path) -> None:
    logger = EventLogger(tmp_path)
    logger.handle(make_event("task_started", {"stage_total": 2}))
    logger.handle(make_event("stage_progress", {"current": 1, "total": 2}))
    lines = log_path(tmp_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["type"] == "task_started"
    assert first["data"] == {"stage_total": 2}
    assert "ts" in first
    assert json.loads(lines[1])["type"] == "stage_progress"


def test_attach_subscribes_to_bus(tmp_path: Path) -> None:
    bus = EventBus()
    unsubscribe = EventLogger(tmp_path).attach(bus)
    bus.publish(make_event("task_completed"))
    unsubscribe()
    bus.publish(make_event("task_failed"))
    lines = log_path(tmp_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
