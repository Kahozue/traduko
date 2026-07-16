"""Live progress messages: one Discord message per running task, edited in
place as events stream in (design doc section 8).

Decision logic lives in ProgressBoard with an injected monotonic clock, so
tests never touch Discord or real time. Edits are throttled per task to
stay under Discord's per-channel edit rate limit; terminal events always
go out and end the tracking.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from . import render

logger = logging.getLogger(__name__)

TERMINAL_LINES = {
    "task_completed": "已完成",
    "task_failed": "失敗",
    "task_canceled": "已取消",
    "task_paused": "已暫停",
    "task_waiting_review": "停於人工檢查點",
}


@dataclass
class _TaskState:
    label: str
    stage_types: list[str]
    stage_total: int
    stage_index: int = 0
    current: int | None = None
    total: int | None = None
    last_edit: float = 0.0


@dataclass(frozen=True)
class Action:
    kind: str  # "post" | "edit" | "close"
    key: tuple[str, str]
    content: str


class ProgressBoard:
    def __init__(self, clock=time.monotonic, min_edit_interval: float = 2.0) -> None:
        self._clock = clock
        self._min_edit_interval = min_edit_interval
        self._tasks: dict[tuple[str, str], _TaskState] = {}

    def handle(self, payload: dict, record: dict | None = None) -> Action | None:
        key = (payload["project"], payload["task_id"])
        etype = payload["type"]
        data = payload.get("data", {})
        if etype == "task_started":
            stage_types = [s["type"] for s in (record or {}).get("stages", [])]
            state = _TaskState(
                label=render.task_label(record) if record else f"{key[0]}/{key[1]}",
                stage_types=stage_types,
                stage_total=data.get("stage_total", len(stage_types)) or 1,
            )
            self._tasks[key] = state
            return Action("post", key, self._content(state, "執行中"))
        state = self._tasks.get(key)
        if state is None:
            return None
        if etype in TERMINAL_LINES:
            del self._tasks[key]
            return Action("close", key, self._content(state, TERMINAL_LINES[etype]))
        if etype == "stage_started":
            state.stage_index = data["stage_index"]
            state.current = None
            state.total = None
            state.last_edit = self._clock()
            return Action("edit", key, self._content(state, "執行中"))
        if etype == "stage_progress":
            state.stage_index = data["stage_index"]
            state.current = data["current"]
            state.total = data["total"]
            now = self._clock()
            if now - state.last_edit < self._min_edit_interval:
                return None
            state.last_edit = now
            return Action("edit", key, self._content(state, "執行中"))
        if etype == "stage_completed":
            state.stage_index = data["stage_index"]
            state.last_edit = self._clock()
            return Action("edit", key, self._content(state, "執行中"))
        return None

    def _content(self, state: _TaskState, status_line: str) -> str:
        stage_no = state.stage_index + 1
        if state.stage_index < len(state.stage_types):
            stage_name = render.stage_label(state.stage_types[state.stage_index])
        else:
            stage_name = f"第 {stage_no} 階段"
        lines = [
            state.label,
            f"{status_line}｜階段 {stage_no}/{state.stage_total}：{stage_name}",
        ]
        if state.current is not None and state.total:
            lines.append(
                f"{render.bar(state.current, state.total)} {state.current}/{state.total}"
            )
        return "\n".join(lines)


class Messenger(Protocol):
    async def post(self, content: str) -> object: ...

    async def edit(self, ref: object, content: str) -> None: ...


async def consume_events(
    queue: asyncio.Queue,
    api,
    messenger: Messenger,
    board: ProgressBoard | None = None,
) -> None:
    """Drain broadcaster payloads until a None sentinel or cancellation."""
    board = board or ProgressBoard()
    refs: dict[tuple[str, str], object] = {}
    while True:
        payload = await queue.get()
        if payload is None:
            return
        try:
            record = None
            if payload.get("type") == "task_started":
                record = await api.get_task(payload["project"], payload["task_id"])
            action = board.handle(payload, record)
            if action is None:
                continue
            if action.kind == "post" or action.key not in refs:
                refs[action.key] = await messenger.post(action.content)
            else:
                await messenger.edit(refs[action.key], action.content)
            if action.kind == "close":
                refs.pop(action.key, None)
        except Exception:
            logger.warning("progress update failed", exc_info=True)
