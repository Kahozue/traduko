"""In-process event bus. External channels subscribe to this later."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger(__name__)

EVENT_TYPES = frozenset(
    {
        "task_started",
        "stage_started",
        "stage_progress",
        "stage_completed",
        "task_waiting_review",
        "task_completed",
        "task_failed",
        "task_canceled",
        "task_paused",
        "budget_warning",
        "budget_exceeded",
        "agent_round",
        # Assistant live-progress stream (UI feed only: skipped by the task
        # event logger and excluded from notification defaults).
        "assistant_round",
        "assistant_delta",
        "assistant_text",
        "assistant_tool_started",
        "assistant_tool_finished",
        "assistant_authorization_required",
        "assistant_done",
    }
)


@dataclass(frozen=True)
class Event:
    type: str
    task_id: str
    project: str
    data: dict = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []
        self._lock = Lock()

    def subscribe(self, fn: Callable[[Event], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                if fn in self._subscribers:
                    self._subscribers.remove(fn)

        return unsubscribe

    def publish(self, event: Event) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for fn in subscribers:
            try:
                fn(event)
            except Exception:
                logger.exception("event subscriber failed for %s", event.type)
