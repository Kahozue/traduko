"""Per-task event log: every bus event lands in <task>/logs/events.jsonl.

This is the task-side half of the design doc's log split (section 10);
the core-service system log ships with the service. Unfiltered on
purpose: it is the task's own complete record, progress events included.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from .events import Event, EventBus
from .models import utc_now_iso


class EventLogger:
    def __init__(self, root: Path) -> None:
        self.root = root

    def handle(self, event: Event) -> None:
        # Assistant live-progress events are a UI feed, not task history;
        # logging them would grow junk dirs under projects/assistant.
        if event.type.startswith("assistant_"):
            return
        log_dir = (
            self.root / "projects" / event.project / "tasks" / event.task_id / "logs"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        entry = {"ts": utc_now_iso(), "type": event.type, "data": event.data}
        with (log_dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def attach(self, bus: EventBus) -> Callable[[], None]:
        return bus.subscribe(self.handle)
