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


def test_run_attaches_images_to_opening_user_message(tmp_path: Path) -> None:
    runner, _, _ = make_runner(tmp_path, ['{"done": true, "summary": "ok"}'])
    seen = {}
    inner_chat = runner.provider.chat

    def capture(request):
        seen["messages"] = request.messages
        return inner_chat(request)

    runner.provider.chat = capture
    result = runner.run("Goal.", images=["/abs/shot.png"])
    assert result.converged is True
    assert seen["messages"][0].images == []
    assert seen["messages"][1].images == ["/abs/shot.png"]


def make_event_runner(tmp_path: Path, responses: list[str]):
    events: list[tuple[str, dict]] = []
    runner, log, record_path = make_runner(tmp_path, responses)
    runner.on_event = lambda kind, data: events.append((kind, data))
    return runner, log, events


def test_on_event_narrative_tool_and_done(tmp_path: Path) -> None:
    runner, log, events = make_event_runner(
        tmp_path,
        [
            '先看一下任務狀態。\n{"tool": "note", "arguments": {"text": "check"}}',
            '都正常。\n{"done": true, "summary": ""}',
        ],
    )
    result = runner.run("Test goal.")
    assert result.converged is True
    # Empty done summary falls back to the narrative text of the same turn.
    assert result.summary == "都正常。"
    kinds = [kind for kind, _ in events if kind != "delta"]
    assert kinds == ["round", "text", "tool_started", "tool_finished", "done"]
    deltas = [data["text"] for kind, data in events if kind == "delta"]
    assert deltas and all("{" not in text for text in deltas)
    by_kind = dict(events)
    assert by_kind["text"] == {"text": "先看一下任務狀態。"}
    assert by_kind["tool_started"]["tool"] == "note"
    assert by_kind["tool_finished"]["ok"] is True
    assert by_kind["done"]["converged"] is True
    assert log == ["check"]


def test_on_event_round_and_deltas(tmp_path: Path) -> None:
    # The scripted provider has no chat_stream, so the meter degrades to a
    # single delta per turn; the runner still forwards it.
    runner, log, events = make_event_runner(
        tmp_path,
        [
            '{"tool": "end_round", "arguments": {"summary": "pass 1"}}',
            '{"done": true, "summary": "final"}',
        ],
    )
    result = runner.run("Test goal.")
    assert result.summary == "final"
    rounds = [data["round"] for kind, data in events if kind == "round"]
    assert rounds == [1, 2]
    deltas = [data["text"] for kind, data in events if kind == "delta"]
    # Protocol JSON must never leak into user-facing deltas.
    assert all("{" not in text for text in deltas)


def test_on_event_tool_error_reports_not_ok(tmp_path: Path) -> None:
    runner, log, events = make_event_runner(
        tmp_path,
        [
            '{"tool": "missing_tool", "arguments": {}}',
            '{"done": true, "summary": "gave up"}',
        ],
    )
    runner.run("Test goal.")
    finished = [data for kind, data in events if kind == "tool_finished"]
    assert finished and finished[0]["ok"] is False
