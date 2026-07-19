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

from .. import mcphub, skillhub
from ..budget import BudgetMeter
from ..config import CoreConfig
from ..events import Event
from ..llm import LLMError, create_llm
from ..preflight import run_preflight as compute_preflight
from ..proposals import (
    CONFIRMED_VIA_PROPOSAL_ERROR,
    patch_grants_confirmation,
    propose_config,
)
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
# max_turns bounds LLM calls per message (every tool call costs one turn); 12
# proved too tight for real diagnostics passes (scan tasks + budget + config
# already burns five), so a turn-limited reply cut real answers short.
ASSISTANT_LIMITS = AgentLimits(max_rounds=1, max_turns=24)

# System prompts keyed by the UI language the message was sent from. The
# reply language is pinned to the interface language (not auto-detected from
# the operator's text: small models routinely answer Traditional-Chinese
# operators in Simplified Chinese). The mechanical tool protocol appended by
# the runner stays English on purpose — it is a wire format, like code.
SYSTEM_PROMPTS: dict[str, str] = {
    "en": """\
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
instead of guessing about the state of the system. You can also set up \
work the operator asks for: list_profiles shows the available pipelines, \
and create_task creates a new task from one. A task you create is left \
PENDING for the operator to review and run — you never start it yourself, \
so confirm the input file, profile, and target settings before creating \
it. When the operator attaches a file, its path appears in their message \
as "[attached files: ...]"; use that path as create_task's input_path. \
Attached images from the current message are also sent to you as images, \
so if you can see them, read them directly (e.g. a settings screenshot) \
instead of asking the operator to describe them.

Language rule (highest priority): always reply in English, even if the \
operator writes in another language. Never use emoji.""",
    "zh-TW": """\
你是 Traduko 的內建操作助理，協助操作者了解與調整本機的 Traduko 安裝：\
任務狀態、預算用量、設定、日誌與 preflight 診斷。

鐵則：你永遠不能自行修改設定。唯一的修改途徑是呼叫 propose_config_change \
工具，它會建立一筆待審提案，操作者必須在應用程式面板中審核核准後才會生效。\
絕不可宣稱或暗示你已經套用、儲存或修改了任何設定；最多只能說你已提交提案，\
正在等待核准。

回答前先用唯讀工具（list_tasks、task_detail、budget_status、read_config、\
read_logs、run_preflight）蒐集事實，不要猜測系統狀態。你也可以替操作者準備\
工作：list_profiles 列出可用的管線 profile，create_task 依 profile 建立新\
任務。你建立的任務會停在 PENDING 狀態，由操作者確認後執行——你永遠不能自行\
啟動任務，所以建立前先確認輸入檔案、profile 與目標設定。操作者附加檔案時，\
路徑會以「[attached files: ...]」出現在訊息中；把該路徑當作 create_task 的 \
input_path。目前訊息附加的圖片也會直接傳給你，看得到就直接讀取內容（例如\
設定截圖），不要再要求操作者描述。

語言規則（最高優先）：一律使用繁體中文（台灣用語）回覆，即使操作者使用其他\
語言。禁止使用任何 emoji。""",
    "ja": """\
あなたは Traduko の内蔵オペレーションアシスタントです。オペレーターが\
ローカルの Traduko 環境を把握・調整できるよう支援します：タスク状態、\
予算使用量、設定、ログ、preflight 診断。

鉄則：設定を自分で変更することは決してできません。変更の唯一の手段は \
propose_config_change ツールの呼び出しであり、これは承認待ちの提案を\
作成するだけです。オペレーターがアプリのパネルで確認・承認して初めて\
反映されます。設定を適用・保存・変更したと述べたり示唆したりしては\
いけません。言えるのは「提案を提出し、承認待ちである」ことまでです。

回答の前に、読み取り専用ツール（list_tasks、task_detail、budget_status、\
read_config、read_logs、run_preflight）で事実を収集し、システム状態を\
推測で語らないでください。オペレーターの依頼があれば作業の準備もできます：\
list_profiles で利用可能なパイプライン profile を一覧し、create_task で\
新しいタスクを作成します。作成したタスクは PENDING のまま残り、実行は\
オペレーターが確認して行います。あなたがタスクを開始することは決して\
ありません。作成前に入力ファイル・profile・目標設定を確認してください。\
オペレーターがファイルを添付すると、そのパスはメッセージ内に \
「[attached files: ...]」として現れます。そのパスを create_task の \
input_path に使ってください。現在のメッセージに添付された画像はあなたにも\
送られるので、見える場合は（設定のスクリーンショットなど）内容を直接\
読み取り、説明を求め直さないでください。

言語ルール（最優先）：オペレーターが他の言語で書いた場合でも、必ず日本語で\
返答してください。絵文字は一切使用しないでください。""",
}

DEFAULT_LANG = "zh-TW"
# Kept as an alias for callers/tests that referenced the single-prompt name.
SYSTEM_PROMPT = SYSTEM_PROMPTS["en"]

_SECRET_MARKERS = ("key", "token", "password", "secret", "webhook")


class AssistantUnavailable(Exception):
    """No usable LLM provider is configured for the assistant to run on."""


class AssistantLLMError(Exception):
    """The assistant's provider was reachable but the chat call failed.

    Distinct from AssistantUnavailable (no provider at all): here a provider
    is configured but the request was rejected — a bad key, an unknown
    model, exhausted quota, a network fault. The raw provider message is
    preserved so the UI can classify it into readable wording."""


def _is_secret_key(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def _redact(value: object) -> object:
    """Recursively replace secret-looking string values with a placeholder.

    A key counts as secret if its lowercased name contains "key", "token",
    "password", "secret" or "webhook" (webhook URLs are bearer-capable
    credentials); only non-empty string values are replaced, so nested
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
                "passwords, secrets, webhook URLs) redacted."
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


def _build_propose_tool(
    ws: Workspace,
    proposal_ids: list[str],
    on_proposal: Callable[[str], None] | None = None,
) -> AgentTool:
    """The one write tool: files a pending proposal, never touches config.

    `proposal_ids` is a per-run accumulator owned by the caller
    (`run_assistant_message`); every proposal created during this run gets
    appended so the caller can report and persist which ids this message
    produced. `on_proposal` fires per filed proposal so the live event feed
    can raise the authorization card immediately.
    """

    def propose_config_change(args: dict) -> str:
        patch = args.get("patch")
        if not isinstance(patch, dict):
            raise ToolError("patch must be an object (a partial config tree)")
        # First layer of the confirmation gate (proposals.propose_config is
        # the second): `confirmed` on skills/mcp_servers must never travel
        # through the proposal channel, only the settings panel grants it.
        if patch_grants_confirmation(patch):
            raise ToolError(CONFIRMED_VIA_PROPOSAL_ERROR)
        reason = str(args.get("reason", ""))
        try:
            proposal = propose_config(ws.root, patch, reason)
        except ValueError as error:
            # Covers pydantic's ValidationError (a ValueError subclass) for
            # invalid merges and propose_config's own confirmed-gate error.
            raise ToolError(str(error)) from None
        proposal_ids.append(proposal["id"])
        if on_proposal is not None:
            on_proposal(proposal["id"])
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
            "the config, e.g. {\"budget\": {\"monthly_usd_limit\": 50}}. "
            "`confirmed` on skills or mcp_servers entries cannot be set "
            "through the proposal channel: confirmation is granted only from "
            "the settings panel, so propose `enabled` only."
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


def _build_action_tools(ws: Workspace, created_task_ids: list[str]) -> list[AgentTool]:
    """Tools that change task state (not config). These create work the user
    asked for — a pending task — but never run it: the task lands in the
    normal PENDING state for the operator to review and start, so nothing
    irreversible happens without a human. Config still only moves through the
    proposal channel."""
    from ..profiles import load_profile, stage_records_from

    def list_profiles(args: dict) -> str:
        names = sorted(path.stem for path in (ws.root / "profiles").glob("*.yaml"))
        return json.dumps(names, ensure_ascii=False)

    def create_task(args: dict) -> str:
        input_path = Path(str(args.get("input_path", "")))
        profile_name = str(args.get("profile", ""))
        if not input_path.exists():
            raise ToolError(f"input not found: {input_path}")
        try:
            profile = load_profile(ws.root, profile_name)
        except FileNotFoundError:
            raise ToolError(f"profile not found: {profile_name}") from None
        record = ws.store.create(
            project=str(args.get("project") or ws.config.default_project),
            input_path=str(input_path.resolve()),
            profile_name=profile_name,
            stages=stage_records_from(profile),
            name=(str(args["name"]) if args.get("name") else None),
        )
        created_task_ids.append(record.id)
        return json.dumps(
            {
                "task_id": record.id,
                "project": record.project,
                "status": record.status.value,
                "note": "task created in pending state; the operator must run it",
            },
            ensure_ascii=False,
        )

    def rerun_task(args: dict) -> str:
        project = str(args["project"])
        task_id = str(args["task_id"])
        try:
            record = ws.store.load(project, task_id)
        except FileNotFoundError:
            raise ToolError(f"task not found: {project}/{task_id}") from None
        try:
            ws.store.reset_for_rerun(record)
        except ValueError as error:
            # Only a COMPLETED task can be rerun; surface the reason to the model
            # rather than half-resetting anything.
            raise ToolError(str(error)) from None
        return json.dumps(
            {
                "task_id": record.id,
                "project": record.project,
                "status": record.status.value,
                "note": "task reset to pending; the operator must run it",
            },
            ensure_ascii=False,
        )

    return [
        AgentTool(
            name="list_profiles",
            description="List the pipeline profile names available for new tasks.",
            parameters={},
            handler=_safe(list_profiles),
        ),
        AgentTool(
            name="create_task",
            description=(
                "Create a new task from a pipeline profile. The task is left "
                "PENDING for the operator to review and run; it is never "
                "started automatically. Use an attached file path as "
                "input_path when the operator gave one."
            ),
            parameters={
                "input_path": {
                    "type": "string",
                    "required": True,
                    "description": "absolute path to the input file",
                },
                "profile": {
                    "type": "string",
                    "required": True,
                    "description": "pipeline profile name (see list_profiles)",
                },
                "project": {
                    "type": "string",
                    "required": False,
                    "description": "project to file the task under (default project if omitted)",
                },
                "name": {
                    "type": "string",
                    "required": False,
                    "description": "human-friendly task name",
                },
            },
            handler=_safe(create_task),
        ),
        AgentTool(
            name="rerun_task",
            description=(
                "Reset a COMPLETED task's stages back to PENDING so the whole "
                "pipeline can run again. The task is left PENDING for the "
                "operator to run; it is never started automatically. Editor "
                "edits to the translation or subtitles are overwritten on the "
                "next run."
            ),
            parameters={
                "project": {
                    "type": "string",
                    "required": True,
                    "description": "project the task is filed under",
                },
                "task_id": {
                    "type": "string",
                    "required": True,
                    "description": "id of the completed task to rerun",
                },
            },
            handler=_safe(rerun_task),
        ),
    ]


def _build_registry(
    ws: Workspace,
    proposal_ids: list[str],
    created_task_ids: list[str],
    on_proposal: Callable[[str], None] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in build_assistant_tools(ws):
        registry.register(tool)
    registry.register(_build_propose_tool(ws, proposal_ids, on_proposal))
    for tool in _build_action_tools(ws, created_task_ids):
        registry.register(tool)
    for tool in mcphub.active_tools():
        registry.register(tool)
    for tool in skillhub.active_tools():
        registry.register(tool)
    return registry


# Visual classification for the live tool-activity indicator. External MCP
# tools (dotted names) count as "execute" — the conservative badge for
# capabilities we do not control.
_TOOL_KINDS = {
    "list_tasks": "read",
    "task_detail": "read",
    "budget_status": "read",
    "read_config": "read",
    "read_logs": "read",
    "run_preflight": "read",
    "list_profiles": "read",
    "use_skill": "read",
    "propose_config_change": "write",
    "create_task": "execute",
    "rerun_task": "execute",
}


def tool_kind(name: str) -> str:
    return _TOOL_KINDS.get(name, "execute")


def _resolve_default_llm(config: CoreConfig):
    """Pick the assistant's LLM provider from `config.llm_providers`.

    Rule: the provider the user chose in settings (`config.default_provider`)
    wins; then the "default" key if present, then the sole entry if there is
    exactly one, then the first key in sorted order. The fallback chain keeps
    old configs working, but an explicit default_provider must never lose to
    alphabetical order (the pre-fix bug: "Claude" sorted ahead of the chosen
    provider, so the assistant always ran claude-haiku-4-5). Mirrors
    `stages/common.py:resolve_llm`'s handling of an entry dict (pop "model"
    before handing the rest to `create_llm`).
    """
    providers = config.llm_providers
    if not providers:
        raise AssistantUnavailable(
            "no llm_providers configured; add one under config/core.yaml "
            "before using the assistant"
        )
    default = config.default_provider
    if default and default in providers:
        key = default
    elif "default" in providers:
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


def _load_history(ws: Workspace) -> list[dict]:
    # Active-session messages, migrating the legacy history.json on first use.
    from . import assistant_store

    return assistant_store.load_messages(ws)


def _save_history(ws: Workspace, messages: list[dict]) -> None:
    from . import assistant_store

    assistant_store.save_messages(ws, messages)


def load_history(ws: Workspace) -> list[dict]:
    """Public accessor for the service layer: the active session's message
    list (same shape as the goal transcript loader), or [] if empty."""
    return _load_history(ws)


def clear_history(ws: Workspace) -> None:
    """Reset the active session to an empty message list. Run records under
    `assistant/runs/` and other sessions are untouched."""
    _save_history(ws, [])


def _build_goal(
    history: list[dict],
    text: str,
    *,
    images: list[str] | None = None,
    lang: str = DEFAULT_LANG,
) -> str:
    block = skillhub.active_prompt_block()
    transcript = ["Conversation so far:"]
    for message in history[-HISTORY_TRANSCRIPT_LIMIT:]:
        role = "USER" if message.get("role") == "user" else "ASSISTANT"
        line = str(message.get("text", ""))
        attached = message.get("images")
        if isinstance(attached, list) and attached:
            line += f"  [attached files: {', '.join(str(p) for p in attached)}]"
        transcript.append(f"{role}: {line}")
    user_line = text
    if images:
        user_line += f"  [attached files: {', '.join(images)}]"
    transcript.append(f"USER: {user_line}")
    parts = [SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS[DEFAULT_LANG])]
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


def run_assistant_message(
    ws: Workspace,
    text: str,
    *,
    edit_index: int | None = None,
    images: list[str] | None = None,
    lang: str = DEFAULT_LANG,
) -> dict:
    """Run one assistant turn: load history, run the agent, persist history.

    Never mutates config itself; any write the model wants goes through
    `propose_config_change` and stays pending until a human approves it.
    Returns `{"reply", "proposal_ids", "converged", "reason"}`.

    `edit_index`, when given, truncates the active session at that message
    index before the turn runs — the edit-and-resend path, where the user
    rewrote an earlier message and everything after it is discarded.
    `images` are absolute paths to image files attached to this message;
    they are recorded on the user message, noted as paths in the goal
    transcript, and sent as image content on this turn's opening message
    (vision-capable models see the pixels; text-only endpoints reject the
    call, which surfaces as AssistantLLMError). Images from earlier history
    messages stay path-only. `lang` is the UI language the message was sent
    from; it picks the system prompt and thereby the reply language.
    """
    provider, model = _resolve_default_llm(ws.config)
    if edit_index is not None:
        from . import assistant_store

        assistant_store.truncate_after(
            ws, assistant_store.active_session_id(ws), edit_index
        )
    history = _load_history(ws)
    goal = _build_goal(history, text, images=images, lang=lang)

    from . import assistant_store

    session_id = assistant_store.active_session_id(ws)

    def publish(event_type: str, data: dict) -> None:
        ws.bus.publish(
            Event(
                type=event_type,
                task_id=session_id,
                project=ASSISTANT_PROJECT,
                data=data,
            )
        )

    proposal_ids: list[str] = []
    created_task_ids: list[str] = []
    registry = _build_registry(
        ws,
        proposal_ids,
        created_task_ids,
        on_proposal=lambda proposal_id: publish(
            "assistant_authorization_required", {"proposal_id": proposal_id}
        ),
    )
    meter = BudgetMeter(ws.root, ws.bus, ws.config)
    task_id = "assistant-" + datetime.now().strftime("%Y%m")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    recorder = AgentRunRecorder(ws.root / "assistant" / "runs", run_id=run_id)

    # Narrative texts the model addressed to the user mid-run; persisted as
    # their own assistant messages so the conversation reads as the
    # multi-step flow it was.
    intermediate_texts: list[str] = []

    def on_event(kind: str, data: dict) -> None:
        if kind == "text":
            intermediate_texts.append(str(data.get("text", "")))
            publish("assistant_text", data)
        elif kind == "delta":
            publish("assistant_delta", data)
        elif kind == "tool_started":
            publish(
                "assistant_tool_started",
                {**data, "kind": tool_kind(str(data.get("tool", "")))},
            )
        elif kind == "tool_finished":
            publish("assistant_tool_finished", data)
        elif kind == "round":
            publish("assistant_round", data)
        elif kind == "done":
            publish("assistant_done", data)

    runner = AgentRunner(
        provider=provider,
        meter=meter,
        model=model,
        project=ASSISTANT_PROJECT,
        task_id=task_id,
        registry=registry,
        recorder=recorder,
        limits=ASSISTANT_LIMITS,
        on_event=on_event,
    )
    try:
        result = runner.run(goal, images=images)
    except LLMError as error:
        # The provider was reachable enough to try but rejected the call (bad
        # key, unknown model, quota). Surface the raw message so the UI layer
        # can classify it; the turn is not persisted to history because no
        # assistant reply exists.
        raise AssistantLLMError(str(error)) from error
    # The assistant is a single-round Q&A agent (max_rounds=1). "round" and
    # "turn" are convergence machinery the shared runner inherits from the
    # proofread agent, which genuinely loops scan/fix passes; a conversational
    # assistant does not. So when the model closes its one round with
    # end_round instead of the near-synonymous done, the runner reports
    # reason="max_rounds" — but the closing summary (or the prose it wrote
    # ahead of the end_round call) IS the answer. Treat that as answered, not
    # as the truncation it looks like. max_turns is different: it fires at the
    # top of the loop before any final answer exists, so there is nothing to
    # salvage and the canned "couldn't finish" reply is correct.
    answered = result.converged or (
        result.reason == "max_rounds" and result.summary.strip() != ""
    )
    reply = result.summary if answered else _not_converged_reply(result.reason)

    user_message = {
        "role": "user",
        "text": text,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if images:
        user_message["images"] = list(images)
    history.append(user_message)
    for narrative in intermediate_texts:
        if narrative:
            history.append(
                {
                    "role": "assistant",
                    "text": narrative,
                    "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "model": model,
                }
            )
    history.append(
        {
            "role": "assistant",
            "text": reply,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "proposal_ids": proposal_ids,
            # Record which model produced this reply so the panel can show it;
            # older history rows without this field render no model chip.
            "model": model,
        }
    )
    _save_history(ws, history)

    return {
        "reply": reply,
        "proposal_ids": proposal_ids,
        "created_task_ids": created_task_ids,
        # `answered`, not the raw runner verdict: a single-round end_round that
        # produced a summary counts as a real answer for the UI. `reason`
        # stays the raw runner reason for diagnostics (the run record already
        # logged it too).
        "converged": answered,
        "reason": result.reason,
    }
