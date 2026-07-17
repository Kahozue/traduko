"""Built-in assistant: read-only diagnostic tools (v2-06, task 1).

The assistant is an AgentRunner application, like proofread, but its job
is answering questions about the running system rather than editing task
content. Every tool here only reads state through the same code paths the
service already uses (index, store, BudgetMeter, run_preflight) so the
assistant never sees a different answer than the UI does. Nothing here
mutates anything; `propose_config_change` (the one tool that changes
state, gated behind human approval) and the system prompt/message loop
that wire this list into a running agent belong to a later task.

`build_assistant_tools` intentionally returns a plain list rather than a
ToolRegistry: the next task appends the proposal tool (and, likely,
mcphub.active_tools()/skillhub.active_tools()) before registering
everything, and a list is the simplest thing to concatenate.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from ..budget import BudgetMeter
from ..preflight import run_preflight as compute_preflight
from ..workspace import Workspace
from .tools import AgentTool, ToolError

DEFAULT_LOG_LINES = 50
MAX_LOG_LINES = 500
# How many of a task's most recent events to surface in task_detail; a
# diagnostic tool feeding an LLM prompt needs a bounded tail, not the
# service's full-history endpoint default.
TASK_DETAIL_EVENTS_LIMIT = 20

_SECRET_MARKERS = ("key", "token", "password")


def _is_secret_key(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _redact(value: object) -> object:
    """Recursively replace secret-looking string values with a placeholder.

    A key counts as secret if its lowercased name contains "key", "token"
    or "password"; only non-empty string values are replaced, so nested
    dicts (llm_providers, mcp_servers, ...) and lists of dicts are covered
    without needing a hardcoded list of sections.
    """
    if isinstance(value, dict):
        result = {}
        for key, sub in value.items():
            if isinstance(sub, str) and sub and _is_secret_key(key):
                result[key] = "<redacted>"
            else:
                result[key] = _redact(sub)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _safe(handler: Callable[[dict], str]) -> Callable[[dict], str]:
    """Wrap a handler so any unexpected exception becomes a ToolError.

    All assistant tools are read-only diagnostics; a bug or an unusual
    on-disk state (a stale index entry, a corrupt log line) must not
    escape as some other exception type and crash the agent loop.
    """

    def wrapped(args: dict) -> str:
        try:
            return handler(args)
        except ToolError:
            raise
        except Exception as error:  # noqa: BLE001 - deliberate catch-all boundary
            raise ToolError(str(error)) from error

    return wrapped


def build_assistant_tools(ws: Workspace) -> list[AgentTool]:
    def list_tasks(args: dict) -> str:
        project = args.get("project")
        rows = ws.index.list(project=project)
        tasks = []
        for row in rows:
            try:
                record = ws.store.load(row["project"], row["id"])
            except FileNotFoundError:
                # Index entry with no backing task.json (e.g. deleted out of
                # band); skip it rather than fail the whole listing.
                continue
            tasks.append(
                {
                    "id": record.id,
                    "project": record.project,
                    "title": record.name,
                    "status": record.status.value,
                    "stages": [
                        {"type": stage.type, "status": stage.status.value}
                        for stage in record.stages
                    ],
                }
            )
        return json.dumps(tasks, ensure_ascii=False)

    def task_detail(args: dict) -> str:
        project = str(args["project"])
        task_id = str(args["task_id"])
        try:
            record = ws.store.load(project, task_id)
        except FileNotFoundError:
            raise ToolError(f"task not found: {project}/{task_id}") from None
        log_path = ws.store.task_dir(project, task_id) / "logs" / "events.jsonl"
        events: list[dict] = []
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            events = [
                json.loads(line)
                for line in lines[-TASK_DETAIL_EVENTS_LIMIT:]
                if line.strip()
            ]
        return json.dumps(
            {"task": record.model_dump(), "recent_events": events}, ensure_ascii=False
        )

    def budget_status(args: dict) -> str:
        meter = BudgetMeter(ws.root, ws.bus, ws.config)
        tasks = [
            {
                "task_id": row["id"],
                "project": row["project"],
                "name": row.get("name") or None,
                "remaining_usd": meter.remaining_usd(row["id"]),
            }
            for row in ws.index.list()
        ]
        return json.dumps(
            {
                "month_usd": meter.month_usage_usd(),
                "task_usd_limit": ws.config.budget.task_usd_limit,
                "monthly_usd_limit": ws.config.budget.monthly_usd_limit,
                "tasks": tasks,
            },
            ensure_ascii=False,
        )

    def read_config(args: dict) -> str:
        return json.dumps(_redact(ws.config.model_dump()), ensure_ascii=False)

    def read_logs(args: dict) -> str:
        raw = args.get("lines", DEFAULT_LOG_LINES)
        try:
            requested = int(raw)
        except (TypeError, ValueError):
            raise ToolError("lines must be an integer") from None
        clamped = max(1, min(MAX_LOG_LINES, requested))
        path: Path = ws.root / "logs" / "core.log"
        if not path.exists():
            return "no log file: core.log has not been created yet"
        lines = path.read_text(encoding="utf-8").splitlines()
        return json.dumps(lines[-clamped:], ensure_ascii=False)

    def run_preflight_tool(args: dict) -> str:
        project = str(args["project"])
        task_id = str(args["task_id"])
        try:
            record = ws.store.load(project, task_id)
        except FileNotFoundError:
            raise ToolError(f"task not found: {project}/{task_id}") from None
        report = compute_preflight(record, ws.root)
        return json.dumps(
            {"ok": report.ok, "checks": [asdict(check) for check in report.checks]},
            ensure_ascii=False,
        )

    return [
        AgentTool(
            name="list_tasks",
            description="List tasks (id, title, status, stage list), optionally filtered by project.",
            parameters={
                "project": {
                    "type": "string",
                    "required": False,
                    "description": "restrict to this project",
                },
            },
            handler=_safe(list_tasks),
        ),
        AgentTool(
            name="task_detail",
            description="Full task record plus its most recent logged events.",
            parameters={
                "project": {"type": "string", "required": True, "description": "task's project"},
                "task_id": {"type": "string", "required": True, "description": "task id"},
            },
            handler=_safe(task_detail),
        ),
        AgentTool(
            name="budget_status",
            description="Monthly usage, configured limits, and per-task remaining budget.",
            parameters={},
            handler=_safe(budget_status),
        ),
        AgentTool(
            name="read_config",
            description=(
                "Dump the live config with secret-looking values (keys, tokens, "
                "passwords) redacted."
            ),
            parameters={},
            handler=_safe(read_config),
        ),
        AgentTool(
            name="read_logs",
            description="Tail the service log (default 50 lines, max 500).",
            parameters={
                "lines": {
                    "type": "integer",
                    "required": False,
                    "description": "number of trailing lines, clamped to [1, 500]",
                },
            },
            handler=_safe(read_logs),
        ),
        AgentTool(
            name="run_preflight",
            description="Run preflight checks for a task and return the report.",
            parameters={
                "project": {"type": "string", "required": True, "description": "task's project"},
                "task_id": {"type": "string", "required": True, "description": "task id"},
            },
            handler=_safe(run_preflight_tool),
        ),
    ]
