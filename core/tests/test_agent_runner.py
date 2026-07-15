import json
from pathlib import Path

from traduko.agents.recorder import AgentRunRecorder
from traduko.agents.runner import AgentLimits, AgentRunner
from traduko.agents.tools import AgentTool, ToolRegistry
from traduko.budget import BudgetMeter
from traduko.config import BudgetConfig, CoreConfig
from traduko.events import EventBus
from traduko.llm import create_llm


def make_registry(log: list) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        AgentTool(
            name="note",
            description="Record a note.",
            parameters={"text": {"type": "string", "required": True}},
            handler=lambda args: (log.append(args["text"]), f"noted: {args['text']}")[1],
        )
    )
    return registry


def make_runner(
    tmp_path: Path,
    responses: list[str],
    *,
    limits: AgentLimits | None = None,
    budget: BudgetConfig | None = None,
    on_round=None,
) -> tuple[AgentRunner, list, Path]:
    log: list = []
    config = CoreConfig(budget=budget or BudgetConfig())
    meter = BudgetMeter(tmp_path, EventBus(), config)
    recorder = AgentRunRecorder(tmp_path / "agent-runs", "test-run")
    runner = AgentRunner(
        provider=create_llm({"type": "scripted", "responses": responses}),
        meter=meter,
        model="test-model",
        project="p",
        task_id="t1",
        registry=make_registry(log),
        recorder=recorder,
        limits=limits or AgentLimits(max_rounds=3, max_turns=10),
        on_round=on_round,
    )
    return runner, log, recorder.path


def record_kinds(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line)["kind"] for line in lines]


def test_tool_call_then_done(tmp_path: Path) -> None:
    runner, log, record_path = make_runner(
        tmp_path,
        [
            '{"tool": "note", "arguments": {"text": "first"}}',
            '{"done": true, "summary": "all good"}',
        ],
    )
    result = runner.run("Test goal.")
    assert result.converged is True and result.reason == "done"
    assert result.summary == "all good"
    assert result.rounds == 1 and result.turns == 2
    assert log == ["first"]
    assert record_kinds(record_path) == ["start", "turn", "done", "summary"]


def test_end_round_advances_and_max_rounds_stops(tmp_path: Path) -> None:
    rounds_seen: list[int] = []
    runner, _, _ = make_runner(
        tmp_path,
        [
            '{"tool": "end_round", "arguments": {"summary": "pass 1"}}',
            '{"tool": "end_round", "arguments": {"summary": "pass 2"}}',
        ],
        limits=AgentLimits(max_rounds=2, max_turns=10),
        on_round=rounds_seen.append,
    )
    result = runner.run("Goal")
    assert result.converged is False and result.reason == "max_rounds"
    assert result.rounds == 2
    assert rounds_seen == [1, 2]


def test_tool_error_is_fed_back_not_fatal(tmp_path: Path) -> None:
    runner, log, _ = make_runner(
        tmp_path,
        [
            '{"tool": "note", "arguments": {}}',
            '{"done": true, "summary": "recovered"}',
        ],
    )
    result = runner.run("Goal")
    assert result.converged is True
    assert log == []


def test_protocol_error_retries_once_then_gives_up(tmp_path: Path) -> None:
    runner, _, _ = make_runner(tmp_path, ["not json", "still not json"])
    result = runner.run("Goal")
    assert result.converged is False and result.reason == "protocol_error"


def test_protocol_error_recovers_after_correction(tmp_path: Path) -> None:
    runner, _, _ = make_runner(
        tmp_path, ["garbage", '{"done": true, "summary": "ok"}']
    )
    result = runner.run("Goal")
    assert result.converged is True and result.reason == "done"


def test_max_turns_guard(tmp_path: Path) -> None:
    runner, _, _ = make_runner(
        tmp_path,
        ['{"tool": "note", "arguments": {"text": "x"}}'] * 5,
        limits=AgentLimits(max_rounds=3, max_turns=3),
    )
    result = runner.run("Goal")
    assert result.converged is False and result.reason == "max_turns"
    assert result.turns == 3


def test_budget_exhaustion_converges_early(tmp_path: Path) -> None:
    runner, _, _ = make_runner(
        tmp_path,
        ['{"done": true, "summary": "never reached"}'],
        budget=BudgetConfig(task_usd_limit=0.0),
    )
    result = runner.run("Goal")
    assert result.converged is False and result.reason == "budget"
    assert result.turns == 0


def test_preround_budget_check(tmp_path: Path) -> None:
    runner, _, _ = make_runner(
        tmp_path, [], budget=BudgetConfig(task_usd_limit=1.0)
    )
    assert runner._should_stop_for_budget(0.0) is False
    assert runner._should_stop_for_budget(0.5) is False
    assert runner._should_stop_for_budget(1.5) is True
