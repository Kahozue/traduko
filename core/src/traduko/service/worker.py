"""Background task execution: one worker thread drains a FIFO queue.

One task runs at a time in v1; submission order is preserved. Cancel
tokens are registered at enqueue time, so a queued-but-not-started task
can be canceled too: the executor checks the token before stage one.
Preflight is the API layer's job; the worker only executes.
"""
from __future__ import annotations

import logging
import queue
import threading

from ..executor import CancelToken, PipelineExecutor
from ..models import TaskStatus, transition
from ..workspace import Workspace

logger = logging.getLogger(__name__)


class TaskWorker:
    def __init__(self, ws: Workspace) -> None:
        self._ws = ws
        self._queue: queue.Queue[tuple[str, str] | None] = queue.Queue()
        self._cancels: dict[tuple[str, str], CancelToken] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join()
        self._thread = None

    def enqueue(self, project: str, task_id: str) -> bool:
        key = (project, task_id)
        with self._lock:
            if key in self._cancels:
                return False
            self._cancels[key] = CancelToken()
        self._queue.put(key)
        return True

    def cancel(self, project: str, task_id: str) -> bool:
        with self._lock:
            token = self._cancels.get((project, task_id))
        if token is None:
            return False
        token.set()
        return True

    def is_active(self, project: str, task_id: str) -> bool:
        with self._lock:
            return (project, task_id) in self._cancels

    def _run_loop(self) -> None:
        while True:
            key = self._queue.get()
            if key is None:
                return
            try:
                self._execute(*key)
            except Exception:
                logger.exception("task %s/%s crashed", *key)
                self._mark_failed(*key)
            finally:
                with self._lock:
                    self._cancels.pop(key, None)

    def _execute(self, project: str, task_id: str) -> None:
        with self._lock:
            cancel = self._cancels[(project, task_id)]
        record = self._ws.store.load(project, task_id)
        PipelineExecutor(self._ws.store, self._ws.bus, self._ws.root).run(
            record, cancel
        )

    def _mark_failed(self, project: str, task_id: str) -> None:
        try:
            record = self._ws.store.load(project, task_id)
            transition(record, TaskStatus.FAILED)
            self._ws.store.save(record)
        except Exception:
            logger.exception("could not mark %s/%s as failed", project, task_id)
