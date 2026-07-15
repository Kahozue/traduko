import pytest

from traduko.events import EVENT_TYPES, Event
from traduko.notify import (
    DEFAULT_EVENTS,
    EMAIL_DEFAULT_EVENTS,
    NotifyError,
    create_channel,
    event_payload,
    format_event,
    resolve_events,
)


def make_event(event_type: str = "task_completed", data: dict | None = None) -> Event:
    return Event(type=event_type, task_id="t1", project="p", data=data or {})


def test_format_event_with_data() -> None:
    event = make_event("task_completed", {"stage_total": 3})
    assert format_event(event) == "[traduko] p/t1 task_completed | stage_total=3"


def test_format_event_without_data() -> None:
    assert format_event(make_event("task_started")) == "[traduko] p/t1 task_started"


def test_event_payload_shape() -> None:
    payload = event_payload(make_event("task_failed", {"error": "boom"}))
    assert payload["type"] == "task_failed"
    assert payload["task_id"] == "t1" and payload["project"] == "p"
    assert payload["data"] == {"error": "boom"}
    assert "ts" in payload


def test_default_events_exclude_high_frequency() -> None:
    assert "stage_progress" not in DEFAULT_EVENTS
    assert "agent_round" not in DEFAULT_EVENTS
    assert "task_completed" in DEFAULT_EVENTS
    assert DEFAULT_EVENTS < EVENT_TYPES


def test_email_default_events_are_important_only() -> None:
    assert EMAIL_DEFAULT_EVENTS == frozenset(
        {"task_completed", "task_failed", "budget_warning", "budget_exceeded"}
    )


def test_resolve_events_none_uses_default() -> None:
    assert resolve_events(None, DEFAULT_EVENTS) == DEFAULT_EVENTS


def test_resolve_events_rejects_unknown_names() -> None:
    with pytest.raises(NotifyError, match="task_done"):
        resolve_events(["task_done"], DEFAULT_EVENTS)


def test_create_channel_unknown_type() -> None:
    with pytest.raises(NotifyError):
        create_channel({"type": "carrier-pigeon"})
