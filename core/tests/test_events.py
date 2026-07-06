from traduko.events import Event, EventBus


def make_event(event_type: str = "stage_progress") -> Event:
    return Event(type=event_type, task_id="t1", project="default", data={"current": 1})


def test_publish_reaches_subscribers_in_order() -> None:
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(lambda e: seen.append("a:" + e.type))
    bus.subscribe(lambda e: seen.append("b:" + e.type))
    bus.publish(make_event())
    assert seen == ["a:stage_progress", "b:stage_progress"]


def test_unsubscribe() -> None:
    bus = EventBus()
    seen: list[Event] = []
    unsubscribe = bus.subscribe(seen.append)
    unsubscribe()
    bus.publish(make_event())
    assert seen == []


def test_subscriber_error_does_not_break_others() -> None:
    bus = EventBus()
    seen: list[Event] = []

    def boom(_: Event) -> None:
        raise RuntimeError("boom")

    bus.subscribe(boom)
    bus.subscribe(seen.append)
    bus.publish(make_event())
    assert len(seen) == 1


def test_event_types_include_pause_and_budget() -> None:
    from traduko.events import EVENT_TYPES

    assert {"task_paused", "budget_warning", "budget_exceeded"} <= EVENT_TYPES
