"""Generic agent loop: an LLM drives registered tools until convergence.

Per the design doc an agent run takes a goal, a tool set, convergence
limits and a budget, and yields a result plus a complete run record.
Protocol: the model answers every turn with exactly one JSON object:

    {"tool": "<name>", "arguments": {...}}                     call a tool
    {"tool": "end_round", "arguments": {"summary": "..."}}     close a round
    {"done": true, "summary": "..."}                           goal met

Budget exhaustion converges the run early (the best current result
stands); it never crashes the run.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from ..budget import BudgetExceededError, BudgetMeter
from ..llm import ChatMessage, ChatRequest, LLMProvider
from .recorder import AgentRunRecorder
from .tools import ToolError, ToolRegistry


@dataclass
class AgentLimits:
    max_rounds: int = 3
    max_turns: int = 60


@dataclass
class AgentRunResult:
    converged: bool
    reason: str  # done | max_rounds | max_turns | budget | protocol_error
    summary: str
    rounds: int
    turns: int


_PROTOCOL_HEADER = """

You accomplish the goal above strictly by calling tools.

Reply with exactly ONE JSON object per turn. Before the JSON you may write
one short plain-text sentence to the user describing what you are doing;
it is shown to them live.
- Call a tool: {"tool": "<name>", "arguments": {...}}
- Close the current round after one full scan/fix pass: {"tool": "end_round", "arguments": {"summary": "..."}}
- Finish only when the goal is met: {"done": true, "summary": "..."}
  (write the final reply as the plain text before the JSON and leave
  summary empty, or put it in summary — either works)

AGENT_TOOLS:
"""


def _split_action(content: str) -> tuple[str, dict | None]:
    """Narrative text before the first JSON action, plus the action.

    Returns (text, None) when no valid protocol object is found — the
    caller treats that as a protocol violation, same as before narrative
    prefixes were allowed."""
    start = content.find("{")
    if start == -1:
        return content.strip(), None
    try:
        action, _ = json.JSONDecoder().raw_decode(content[start:])
    except json.JSONDecodeError:
        return content.strip(), None
    if not isinstance(action, dict):
        return content.strip(), None
    if action.get("done") is not True and not isinstance(action.get("tool"), str):
        return content.strip(), None
    return content[:start].strip(), action


def _parse_action(content: str) -> dict | None:
    return _split_action(content)[1]


class AgentRunner:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        meter: BudgetMeter,
        model: str,
        project: str,
        task_id: str,
        registry: ToolRegistry,
        recorder: AgentRunRecorder,
        limits: AgentLimits | None = None,
        temperature: float | None = None,
        on_round: Callable[[int], None] | None = None,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.provider = provider
        self.meter = meter
        self.model = model
        self.project = project
        self.task_id = task_id
        self.registry = registry
        self.recorder = recorder
        self.limits = limits or AgentLimits()
        self.temperature = temperature
        self.on_round = on_round
        # Live progress hook: ("delta"|"text"|"tool_started"|"tool_finished"|
        # "round"|"done", data). Narrative text before each JSON action is
        # forwarded; protocol JSON itself never reaches it.
        self.on_event = on_event

    def _emit(self, kind: str, data: dict) -> None:
        if self.on_event is not None:
            self.on_event(kind, data)

    def _make_delta_gate(self) -> Callable[[str], None]:
        """Forward streamed deltas up to (not including) the first '{':
        narrative streams to the user, protocol JSON stays internal."""
        buffer = ""
        sent = 0
        stopped = False

        def on_delta(piece: str) -> None:
            nonlocal buffer, sent, stopped
            if stopped or self.on_event is None:
                return
            buffer += piece
            brace = buffer.find("{")
            limit = brace if brace != -1 else len(buffer)
            if limit > sent:
                self._emit("delta", {"text": buffer[sent:limit]})
                sent = limit
            if brace != -1:
                stopped = True

        return on_delta

    def _should_stop_for_budget(self, round_cost: float) -> bool:
        remaining = self.meter.remaining_usd(self.task_id)
        return remaining is not None and round_cost > 0 and remaining < round_cost

    def _finish(
        self, converged: bool, reason: str, summary: str, rounds: int, turns: int
    ) -> AgentRunResult:
        self.recorder.record(
            "summary",
            converged=converged,
            reason=reason,
            summary=summary,
            rounds=rounds,
            turns=turns,
        )
        self._emit("done", {"converged": converged, "reason": reason})
        return AgentRunResult(converged, reason, summary, rounds, turns)

    def run(self, goal: str, *, images: list[str] | None = None) -> AgentRunResult:
        """`images` are absolute paths to image files that accompany the goal;
        they ride on the opening user message so vision-capable providers see
        the pixels on every turn of the loop."""
        system = goal + _PROTOCOL_HEADER + json.dumps(
            self.registry.specs(), ensure_ascii=False, indent=2
        )
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content="Begin round 1.", images=list(images or [])),
        ]
        rounds = 1
        turns = 0
        protocol_failures = 0
        round_start_usd = self.meter.task_usage_usd(self.task_id)
        # 4000 keeps the assistant's full system prompt plus a 40-message
        # history transcript inside the start record; 2000 no longer fits.
        self.recorder.record("start", goal=goal[:4000], tools=self.registry.names())
        if self.on_round:
            self.on_round(1)
        self._emit("round", {"round": 1})
        while True:
            if turns >= self.limits.max_turns:
                return self._finish(False, "max_turns", "turn limit reached", rounds, turns)
            request = ChatRequest(
                model=self.model, messages=messages, temperature=self.temperature
            )
            try:
                response = self.meter.chat(
                    self.provider,
                    request,
                    project=self.project,
                    task_id=self.task_id,
                    on_delta=self._make_delta_gate() if self.on_event else None,
                )
            except BudgetExceededError:
                self.recorder.record("budget_stop", round=rounds, turn=turns)
                return self._finish(False, "budget", "budget exhausted", rounds, turns)
            turns += 1
            narrative, action = _split_action(response.content)
            if action is None:
                protocol_failures += 1
                self.recorder.record(
                    "protocol_error", round=rounds, turn=turns,
                    content=response.content[:500],
                )
                if protocol_failures >= 2:
                    return self._finish(
                        False, "protocol_error",
                        "model kept violating the reply protocol", rounds, turns,
                    )
                messages.append(ChatMessage(role="assistant", content=response.content))
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            "Your reply was not a single valid protocol JSON object. "
                            "Reply again, JSON only."
                        ),
                    )
                )
                continue
            protocol_failures = 0
            messages.append(ChatMessage(role="assistant", content=response.content))
            if action.get("done") is True:
                # An empty summary falls back to the narrative text of the
                # same turn, so the final reply can be streamed as plain
                # text ahead of the done marker.
                summary = str(action.get("summary", "")) or narrative
                self.recorder.record("done", round=rounds, turn=turns, summary=summary)
                return self._finish(True, "done", summary, rounds, turns)
            name = action["tool"]
            arguments = action.get("arguments") or {}
            if name == "end_round":
                summary = str(arguments.get("summary", ""))
                round_cost = self.meter.task_usage_usd(self.task_id) - round_start_usd
                self.recorder.record(
                    "round_end", round=rounds, summary=summary,
                    cost_usd=round(round_cost, 6),
                )
                if rounds >= self.limits.max_rounds:
                    return self._finish(False, "max_rounds", summary, rounds, turns)
                if self._should_stop_for_budget(round_cost):
                    return self._finish(
                        False, "budget", "not enough budget for another round",
                        rounds, turns,
                    )
                rounds += 1
                round_start_usd = self.meter.task_usage_usd(self.task_id)
                if self.on_round:
                    self.on_round(rounds)
                self._emit("round", {"round": rounds})
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            f"Round {rounds} begins. Re-verify your fixes, "
                            "then scan for remaining issues."
                        ),
                    )
                )
                continue
            if narrative:
                self._emit("text", {"text": narrative})
            self._emit("tool_started", {"tool": name})
            try:
                result = self.registry.execute(name, arguments)
                tool_ok = True
            except ToolError as error:
                result = f"TOOL_ERROR: {error}"
                tool_ok = False
            except BudgetExceededError:
                self._emit("tool_finished", {"tool": name, "ok": False})
                self.recorder.record("budget_stop", round=rounds, turn=turns, tool=name)
                return self._finish(
                    False, "budget", "budget exhausted during tool call", rounds, turns
                )
            self._emit("tool_finished", {"tool": name, "ok": tool_ok})
            self.recorder.record(
                "turn", round=rounds, turn=turns, tool=name,
                arguments=arguments, result=result[:2000],
            )
            messages.append(
                ChatMessage(role="user", content=f"TOOL_RESULT {name}:\n{result}")
            )
