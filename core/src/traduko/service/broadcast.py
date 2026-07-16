"""Bridge the thread-side EventBus into asyncio WebSocket consumers.

The pipeline runs in a worker thread; each WebSocket connection owns an
asyncio.Queue on the server loop. Bus events are handed over with
call_soon_threadsafe, so publishers never block on slow consumers and
the asyncio side never touches threading primitives. Payload shape is
the same as the webhook notification payload.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

from ..events import Event, EventBus
from ..notify import event_payload


class WsBroadcaster:
    def __init__(self) -> None:
        self._clients: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._next_id = 0

    def register(self) -> tuple[int, asyncio.Queue]:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            client_id = self._next_id
            self._next_id += 1
            self._clients[client_id] = (loop, q)
        return client_id, q

    def unregister(self, client_id: int) -> None:
        with self._lock:
            self._clients.pop(client_id, None)

    def handle(self, event: Event) -> None:
        payload = event_payload(event)
        with self._lock:
            clients = list(self._clients.values())
        for loop, q in clients:
            loop.call_soon_threadsafe(q.put_nowait, payload)

    def attach(self, bus: EventBus) -> Callable[[], None]:
        return bus.subscribe(self.handle)
