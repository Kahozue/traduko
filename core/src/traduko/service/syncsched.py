"""Periodic auto-sync: a daemon thread firing the sync callback at a fixed
interval. Failures are logged and never stop the loop; the callback itself
is responsible for skipping when a manual sync is already running."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class SyncScheduler:
    def __init__(self, interval_seconds: float, fn: Callable[[], None]) -> None:
        self._interval = interval_seconds
        self._fn = fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join()
        self._thread = None

    def _run_loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._fn()
            except Exception:
                logger.exception("scheduled sync failed")
