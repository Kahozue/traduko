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

Reply with exactly ONE JSON object per turn and nothing else:
- Call a tool: {"tool": "<name>", "arguments": {...}}
- Close the current round after one full scan/fix pass: {"tool": "end_round", "arguments": {"summary": "..."}}
- Finish only when the goal is met: {"done": true, "summary": "..."}

AGENT_TOOLS:
"""


def _parse_action(content: str) -> dict | None:
    start = content.find("{")
    if start == -1:
        return None
    try:
        action, _ = json.JSONDecoder().raw_decode(content[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(action, dict):
        return None
    if action.get("done") is True:
        return action
    if isinstance(action.get("tool"), str):
        return action
    return None


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
        while True:
            if turns >= self.limits.max_turns:
                return self._finish(False, "max_turns", "turn limit reached", rounds, turns)
            request = ChatRequest(
                model=self.model, messages=messages, temperature=self.temperature
            )
            try:
                response = self.meter.chat(
                    self.provider, request, project=self.project, task_id=self.task_id
                )
            except BudgetExceededError:
                self.recorder.record("budget_stop", round=rounds, turn=turns)
                return self._finish(False, "budget", "budget exhausted", rounds, turns)
            turns += 1
            action = _parse_action(response.content)
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
                summary = str(action.get("summary", ""))
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
            try:
                result = self.registry.execute(name, arguments)
            except ToolError as error:
                result = f"TOOL_ERROR: {error}"
            except BudgetExceededError:
                self.recorder.record("budget_stop", round=rounds, turn=turns, tool=name)
                return self._finish(
                    False, "budget", "budget exhausted during tool call", rounds, turns
                )
            self.recorder.record(
                "turn", round=rounds, turn=turns, tool=name,
                arguments=arguments, result=result[:2000],
            )
            messages.append(
                ChatMessage(role="user", content=f"TOOL_RESULT {name}:\n{result}")
            )
