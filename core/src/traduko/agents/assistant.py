"""Built-in assistant: read-only diagnostics, proposals, and the message loop.

The assistant is an AgentRunner application, like proofread, but its job
is answering questions about the running system rather than editing task
content. Every read-only tool here only reads state through the same code
paths the service already uses (index, store, BudgetMeter, run_preflight)
so the assistant never sees a different answer than the UI does. The one
tool that changes anything, `propose_config_change`, never writes to
config directly: it files a pending proposal through `proposals.py` that a
human must approve in the UI, same as the config panel's own gated writes.

`build_assistant_tools` intentionally returns a plain list rather than a
ToolRegistry, and deliberately excludes `propose_config_change`: it stays
the fixed set of read-only diagnostics so Task 1's tests keep asserting
exactly that. `run_assistant_message` assembles the full registry (these
six, plus the proposal tool, plus mcphub/skillhub active tools) itself.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .. import mcphub, skillhub
from ..budget import BudgetMeter
from ..config import CoreConfig
from ..fsutil import atomic_write_text
from ..llm import LLMError, create_llm
from ..preflight import run_preflight as compute_preflight
from ..proposals import propose_config
from ..workspace import Workspace
from .recorder import AgentRunRecorder
from .runner import AgentLimits, AgentRunner
from .tools import AgentTool, ToolError, ToolRegistry

DEFAULT_LOG_LINES = 50
MAX_LOG_LINES = 500
# How many of a task's most recent events to surface in task_detail; a
# diagnostic tool feeding an LLM prompt needs a bounded tail, not the
# service's full-history endpoint default.
TASK_DETAIL_EVENTS_LIMIT = 20

# How many of the most recent history messages go into the goal transcript;
# the on-disk history file itself is never trimmed.
HISTORY_TRANSCRIPT_LIMIT = 40
ASSISTANT_PROJECT = "assistant"
ASSISTANT_LIMITS = AgentLimits(max_rounds=1, max_turns=12)

SYSTEM_PROMPT = """\
You are Traduko's built-in operations assistant. You help the operator \
understand and adjust their local Traduko installation: task status, \
budget usage, configuration, logs, and preflight diagnostics.

Hard rule: you can NEVER change the configuration yourself. The only way \
to change anything is to call the propose_config_change tool, which files \
a pending proposal that the operator must review and approve from the \
app's panel before it takes effect. Never say or imply that you have \
already applied, saved, or changed a setting; at most say you have \
submitted a proposal that is awaiting approval.

Use the read-only tools (list_tasks, task_detail, budget_status, \
read_config, read_logs, run_preflight) to gather facts before answering \
instead of guessing about the state of the system. Reply in the same \
language the operator wrote in."""

_SECRET_MARKERS = ("key", "token", "password")


class AssistantUnavailable(Exception):
    """No usable LLM provider is configured for the assistant to run on."""


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


def _build_propose_tool(ws: Workspace, proposal_ids: list[str]) -> AgentTool:
    """The one write tool: files a pending proposal, never touches config.

    `proposal_ids` is a per-run accumulator owned by the caller
    (`run_assistant_message`); every proposal created during this run gets
    appended so the caller can report and persist which ids this message
    produced.
    """

    def propose_config_change(args: dict) -> str:
        patch = args.get("patch")
        if not isinstance(patch, dict):
            raise ToolError("patch must be an object (a partial config tree)")
        reason = str(args.get("reason", ""))
        try:
            proposal = propose_config(ws.root, patch, reason)
        except ValidationError as error:
            raise ToolError(str(error)) from None
        proposal_ids.append(proposal["id"])
        return json.dumps(
            {"proposal_id": proposal["id"], "diff": proposal["diff"]},
            ensure_ascii=False,
        )

    return AgentTool(
        name="propose_config_change",
        description=(
            "File a pending proposal to change the live config. This never "
            "applies the change: a human must approve it in the app's panel "
            "before it takes effect. `patch` uses the same nested shape as "
            "the config, e.g. {\"budget\": {\"monthly_usd_limit\": 50}}."
        ),
        parameters={
            "patch": {
                "type": "object",
                "required": True,
                "description": "partial config tree to merge, same shape as the live config",
            },
            "reason": {
                "type": "string",
                "required": True,
                "description": "why this change is being proposed",
            },
        },
        handler=propose_config_change,
    )


def _build_registry(ws: Workspace, proposal_ids: list[str]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_assistant_tools(ws):
        registry.register(tool)
    registry.register(_build_propose_tool(ws, proposal_ids))
    for tool in mcphub.active_tools():
        registry.register(tool)
    for tool in skillhub.active_tools():
        registry.register(tool)
    return registry


def _resolve_default_llm(config: CoreConfig):
    """Pick the assistant's LLM provider from `config.llm_providers`.

    Rule (no explicit default field exists in config): the "default" key if
    present, else the sole entry if there is exactly one, else the first
    key in sorted order. Mirrors `stages/common.py:resolve_llm`'s handling
    of an entry dict (pop "model" before handing the rest to `create_llm`).
    """
    providers = config.llm_providers
    if not providers:
        raise AssistantUnavailable(
            "no llm_providers configured; add one under config/core.yaml "
            "before using the assistant"
        )
    if "default" in providers:
        key = "default"
    elif len(providers) == 1:
        key = next(iter(providers))
    else:
        key = sorted(providers)[0]
    entry = dict(providers[key])
    model = entry.pop("model", None) or "fake-model"
    try:
        provider = create_llm(entry)
    except LLMError as error:
        raise AssistantUnavailable(str(error)) from error
    return provider, model


def _history_path(ws: Workspace) -> Path:
    return ws.root / "assistant" / "history.json"


def _load_history(ws: Workspace) -> list[dict]:
    path = _history_path(ws)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list):
        return []
    # Per-element validation, not just container-level: a malformed row
    # (wrong type, hand-edited file) is dropped rather than crashing the
    # goal transcript or invalidating rows around it in the same file.
    return [message for message in messages if isinstance(message, dict)]


def _save_history(ws: Workspace, messages: list[dict]) -> None:
    atomic_write_text(
        _history_path(ws), json.dumps({"messages": messages}, ensure_ascii=False, indent=2)
    )


def load_history(ws: Workspace) -> list[dict]:
    """Public accessor for the service layer: the full persisted message
    list (same shape as the goal transcript loader), or [] if no history
    file exists yet."""
    return _load_history(ws)


def clear_history(ws: Workspace) -> None:
    """Reset history.json to an empty message list. Run records under
    `assistant/runs/` are untouched: they are a separate audit trail, not
    part of the conversation transcript."""
    _save_history(ws, [])


def _build_goal(history: list[dict], text: str) -> str:
    block = skillhub.active_prompt_block()
    transcript = ["Conversation so far:"]
    for message in history[-HISTORY_TRANSCRIPT_LIMIT:]:
        role = "USER" if message.get("role") == "user" else "ASSISTANT"
        transcript.append(f"{role}: {message.get('text', '')}")
    transcript.append(f"USER: {text}")
    parts = [SYSTEM_PROMPT]
    if block:
        parts.append(block)
    parts.append("\n".join(transcript))
    return "\n\n".join(parts)


def _not_converged_reply(reason: str) -> str:
    return (
        f"I could not finish processing this message (reason: {reason}). "
        "Nothing was changed without your approval; please try again or "
        "rephrase your request."
    )


def run_assistant_message(ws: Workspace, text: str) -> dict:
    """Run one assistant turn: load history, run the agent, persist history.

    Never mutates config itself; any write the model wants goes through
    `propose_config_change` and stays pending until a human approves it.
    Returns `{"reply", "proposal_ids", "converged", "reason"}`.
    """
    provider, model = _resolve_default_llm(ws.config)
    history = _load_history(ws)
    goal = _build_goal(history, text)

    proposal_ids: list[str] = []
    registry = _build_registry(ws, proposal_ids)
    meter = BudgetMeter(ws.root, ws.bus, ws.config)
    task_id = "assistant-" + datetime.now().strftime("%Y%m")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    recorder = AgentRunRecorder(ws.root / "assistant" / "runs", run_id=run_id)

    runner = AgentRunner(
        provider=provider,
        meter=meter,
        model=model,
        project=ASSISTANT_PROJECT,
        task_id=task_id,
        registry=registry,
        recorder=recorder,
        limits=ASSISTANT_LIMITS,
    )
    result = runner.run(goal)
    reply = result.summary if result.converged else _not_converged_reply(result.reason)

    history.append(
        {
            "role": "user",
            "text": text,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    history.append(
        {
            "role": "assistant",
            "text": reply,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "proposal_ids": proposal_ids,
        }
    )
    _save_history(ws, history)

    return {
        "reply": reply,
        "proposal_ids": proposal_ids,
        "converged": result.converged,
        "reason": result.reason,
    }
