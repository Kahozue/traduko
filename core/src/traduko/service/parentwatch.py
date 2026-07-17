"""Self-termination when a watched parent process dies.

The desktop app spawns the core as a sidecar and kills it on exit, but
that guarantee has holes: a force-quit or crash of the GUI never runs
the kill, and the PyInstaller onefile bootloader can die without taking
the unpacked child along, leaving orphaned cores behind. The watchdog
closes those holes from the inside: the app hands over its own PID at
spawn time and the core exits itself once that PID disappears.

A core started by hand (no parent PID given) never gets a watchdog.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 2.0
_DEFAULT_GRACE = 10.0


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but belongs to someone else.
        return True
    return True


class ParentWatchdog:
    """Poll a parent PID from a daemon thread and terminate this process
    when the parent disappears: SIGTERM first so uvicorn can shut down
    cleanly, then a hard ``os._exit`` after the grace period in case a
    handler swallows the signal."""

    def __init__(
        self,
        parent_pid: int,
        *,
        interval: float = _DEFAULT_INTERVAL,
        grace: float = _DEFAULT_GRACE,
        is_alive: Callable[[int], bool] = pid_alive,
        terminate: Callable[[], None] | None = None,
    ) -> None:
        self._parent_pid = parent_pid
        self._interval = interval
        self._grace = grace
        self._is_alive = is_alive
        self._terminate = terminate if terminate is not None else self._default_terminate
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="parent-watchdog", daemon=True
        )

    @property
    def is_watching(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if not self._is_alive(self._parent_pid):
                logger.warning(
                    "parent process %d is gone; shutting down", self._parent_pid
                )
                self._terminate()
                return

    def _default_terminate(self) -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        # stop() is called on the normal shutdown path, so a set event
        # means the graceful exit is underway and the hard exit can wait.
        if not self._stop.wait(self._grace):
            os._exit(1)
