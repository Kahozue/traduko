"""Notification channels: event bus subscribers that push events outward.

Configured under `notifications.channels` in config/core.yaml:

    notifications:
      channels:
        - type: discord
          webhook_url: https://discord.com/api/webhooks/...
        - type: email
          smtp_host: smtp.example.com
          from_addr: bot@example.com
          to_addrs: [me@example.com]
          password_env: TRADUKO_SMTP_PASSWORD
        - type: webhook
          url: https://example.com/hook
          events: [task_completed, task_failed]

Each channel takes an optional `events` list; unset means the channel
default. Send failures are logged and never break the pipeline. Discord
here is notify-only via a webhook URL; the interactive bot (slash
commands) is a core-service client and lands with the service.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
from collections.abc import Callable
from email.message import EmailMessage

import httpx

from .config import CoreConfig
from .events import EVENT_TYPES, Event, EventBus
from .models import utc_now_iso

logger = logging.getLogger(__name__)


class NotifyError(Exception):
    pass


DEFAULT_EVENTS = frozenset(EVENT_TYPES) - {"stage_progress", "agent_round"}
EMAIL_DEFAULT_EVENTS = frozenset(
    {"task_completed", "task_failed", "budget_warning", "budget_exceeded"}
)

_CHANNELS: dict[str, type] = {}


def register_channel(type_name: str) -> Callable[[type], type]:
    def wrap(cls: type) -> type:
        _CHANNELS[type_name] = cls
        return cls

    return wrap


def create_channel(config: dict, **overrides):
    cfg = {**config, **overrides}
    type_name = cfg.pop("type", None)
    if type_name not in _CHANNELS:
        raise NotifyError(f"unknown notification channel type: {type_name}")
    return _CHANNELS[type_name](**cfg)


def resolve_events(
    events: list[str] | None, default: frozenset[str]
) -> frozenset[str]:
    if events is None:
        return default
    unknown = sorted(set(events) - EVENT_TYPES)
    if unknown:
        raise NotifyError(f"unknown event types: {', '.join(unknown)}")
    return frozenset(events)


def format_event(event: Event) -> str:
    line = f"[traduko] {event.project}/{event.task_id} {event.type}"
    if event.data:
        pairs = " ".join(f"{k}={v}" for k, v in sorted(event.data.items()))
        return f"{line} | {pairs}"
    return line


def event_payload(event: Event) -> dict:
    return {
        "ts": utc_now_iso(),
        "type": event.type,
        "task_id": event.task_id,
        "project": event.project,
        "data": event.data,
    }


@register_channel("webhook")
class WebhookChannel:
    """POST the full event as JSON to an arbitrary URL."""

    def __init__(
        self,
        url: str,
        events: list[str] | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        **_ignored,
    ) -> None:
        self.url = url
        self.events = resolve_events(events, DEFAULT_EVENTS)
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def send(self, event: Event) -> None:
        response = self._client.post(self.url, json=event_payload(event))
        if response.status_code >= 300:
            raise NotifyError(f"webhook failed: http {response.status_code}")


@register_channel("discord")
class DiscordChannel:
    """Post a human-readable line to a Discord webhook URL."""

    def __init__(
        self,
        webhook_url: str,
        events: list[str] | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        **_ignored,
    ) -> None:
        self.webhook_url = webhook_url
        self.events = resolve_events(events, DEFAULT_EVENTS)
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def send(self, event: Event) -> None:
        response = self._client.post(
            self.webhook_url, json={"content": format_event(event)}
        )
        if response.status_code >= 300:
            raise NotifyError(f"discord webhook failed: http {response.status_code}")
