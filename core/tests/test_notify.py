import json
from email.message import EmailMessage

import httpx
import pytest

from traduko.config import CoreConfig, NotificationsConfig
from traduko.events import EVENT_TYPES, Event, EventBus
from traduko.notify import (
    DEFAULT_EVENTS,
    EMAIL_DEFAULT_EVENTS,
    DiscordChannel,
    EmailChannel,
    Notifier,
    NotifyError,
    WebhookChannel,
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


def make_transport(captured: list) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    return httpx.MockTransport(handler)


def test_webhook_posts_event_payload() -> None:
    captured: list[httpx.Request] = []
    channel = WebhookChannel(
        url="http://example.invalid/hook", transport=make_transport(captured)
    )
    channel.send(make_event("task_completed", {"stage_total": 3}))
    assert len(captured) == 1
    assert str(captured[0].url) == "http://example.invalid/hook"
    body = json.loads(captured[0].content)
    assert body["type"] == "task_completed" and body["task_id"] == "t1"
    assert body["data"] == {"stage_total": 3} and "ts" in body


def test_webhook_error_status_raises() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    channel = WebhookChannel(url="http://example.invalid/hook", transport=transport)
    with pytest.raises(NotifyError):
        channel.send(make_event())


def test_webhook_default_and_custom_events() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    default = WebhookChannel(url="http://example.invalid/h", transport=transport)
    assert default.events == DEFAULT_EVENTS
    custom = WebhookChannel(
        url="http://example.invalid/h", events=["task_failed"], transport=transport
    )
    assert custom.events == frozenset({"task_failed"})


def test_discord_posts_content_text() -> None:
    captured: list[httpx.Request] = []
    channel = DiscordChannel(
        webhook_url="http://example.invalid/wh", transport=make_transport(captured)
    )
    channel.send(make_event("task_failed", {"error": "boom"}))
    body = json.loads(captured[0].content)
    assert body == {"content": "[traduko] p/t1 task_failed | error=boom"}


def test_create_channel_builds_webhook() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(204))
    channel = create_channel(
        {"type": "webhook", "url": "http://example.invalid/h"}, transport=transport
    )
    assert isinstance(channel, WebhookChannel)


def make_email_channel(sender, **kwargs) -> EmailChannel:
    return EmailChannel(
        smtp_host="smtp.example.invalid",
        from_addr="bot@example.invalid",
        to_addrs=["a@example.invalid", "b@example.invalid"],
        sender=sender,
        **kwargs,
    )


def test_email_builds_message() -> None:
    sent: list[EmailMessage] = []
    channel = make_email_channel(sent.append)
    channel.send(make_event("task_failed", {"error": "boom"}))
    assert len(sent) == 1
    msg = sent[0]
    assert msg["Subject"] == "[traduko] task_failed: p/t1"
    assert msg["From"] == "bot@example.invalid"
    assert msg["To"] == "a@example.invalid, b@example.invalid"
    body = msg.get_content()
    assert "[traduko] p/t1 task_failed | error=boom" in body
    assert '"error": "boom"' in body


def test_email_default_events_are_important_only_channel() -> None:
    channel = make_email_channel(lambda msg: None)
    assert channel.events == EMAIL_DEFAULT_EVENTS


def test_email_password_from_env(monkeypatch) -> None:
    monkeypatch.setenv("TRADUKO_SMTP_TEST", "sekret")
    channel = make_email_channel(
        lambda msg: None, password_env="TRADUKO_SMTP_TEST"
    )
    assert channel.password == "sekret"


class StubChannel:
    def __init__(self, events: frozenset[str], fail: bool = False) -> None:
        self.events = events
        self.fail = fail
        self.sent: list[Event] = []

    def send(self, event: Event) -> None:
        if self.fail:
            raise NotifyError("boom")
        self.sent.append(event)


def test_notifier_filters_by_channel_events() -> None:
    channel = StubChannel(frozenset({"task_completed"}))
    notifier = Notifier([channel])
    notifier.handle(make_event("task_started"))
    notifier.handle(make_event("task_completed"))
    assert [e.type for e in channel.sent] == ["task_completed"]


def test_notifier_isolates_channel_failures() -> None:
    bad = StubChannel(frozenset({"task_completed"}), fail=True)
    good = StubChannel(frozenset({"task_completed"}))
    notifier = Notifier([bad, good])
    notifier.handle(make_event("task_completed"))
    assert len(good.sent) == 1


def test_notifier_from_config_builds_channels() -> None:
    captured: list[httpx.Request] = []
    config = CoreConfig(
        notifications=NotificationsConfig(
            channels=[
                {
                    "type": "webhook",
                    "url": "http://example.invalid/hook",
                    "events": ["task_completed"],
                }
            ]
        )
    )
    notifier = Notifier.from_config(config, transport=make_transport(captured))
    notifier.handle(make_event("task_completed"))
    notifier.handle(make_event("task_started"))
    assert len(captured) == 1


def test_notifier_from_empty_config_is_noop() -> None:
    notifier = Notifier.from_config(CoreConfig())
    notifier.handle(make_event("task_completed"))
    assert notifier.channels == []


def test_notifier_attach_and_unsubscribe() -> None:
    channel = StubChannel(frozenset({"task_completed"}))
    notifier = Notifier([channel])
    bus = EventBus()
    unsubscribe = notifier.attach(bus)
    bus.publish(make_event("task_completed"))
    unsubscribe()
    bus.publish(make_event("task_completed"))
    assert len(channel.sent) == 1
