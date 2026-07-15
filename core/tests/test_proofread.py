import json
from pathlib import Path

import pytest

from traduko.agents.proofread import (
    ProofreadSettings,
    ProofreadWorkspace,
    build_proofread_tools,
    run_proofread,
)
from traduko.agents.recorder import AgentRunRecorder
from traduko.agents.tools import ToolError
from traduko.budget import BudgetMeter
from traduko.config import CoreConfig
from traduko.events import EventBus
from traduko.glossary import GlossaryEntry
from traduko.llm import create_llm
from traduko.prompts import load_template


def make_segments() -> list[dict]:
    return [
        {
            "id": i, "start": float(i), "end": float(i) + 0.9,
            "source": f"line {i}", "target": f"[T] line {i}",
        }
        for i in range(1, 6)
    ]


def test_read_range_marks_checked_and_labels_context() -> None:
    ws = ProofreadWorkspace(make_segments())
    rows = ws.read_range(2, 3, context=1)
    assert [r["id"] for r in rows] == [1, 2, 3, 4]
    assert rows[0].get("context") is True and "context" not in rows[1]
    assert ws.checked == {2, 3}


def test_read_range_validates_ids() -> None:
    ws = ProofreadWorkspace(make_segments())
    with pytest.raises(ToolError):
        ws.read_range(3, 2)
    with pytest.raises(ToolError):
        ws.read_range(1, 99)


def test_edit_logs_diff_and_round() -> None:
    ws = ProofreadWorkspace(make_segments())
    ws.start_round(2)
    ws.edit(1, "better line", "awkward phrasing")
    assert ws.segments[1]["target"] == "better line"
    assert ws.edits == [
        {
            "id": 1, "before": "[T] line 1", "after": "better line",
            "reason": "awkward phrasing", "round": 2,
        }
    ]


def test_edit_unknown_id() -> None:
    ws = ProofreadWorkspace(make_segments())
    with pytest.raises(ToolError):
        ws.edit(99, "x", "y")


def test_flag_and_round_reset() -> None:
    ws = ProofreadWorkspace(make_segments())
    ws.read_range(1, 5, context=0)
    assert len(ws.checked) == 5
    ws.flag(4, "uncertain idiom")
    ws.start_round(2)
    assert ws.checked == set()
    assert ws.flags == [{"id": 4, "note": "uncertain idiom", "round": 1}]


def test_glossary_violations() -> None:
    ws = ProofreadWorkspace(make_segments())
    entries = [
        GlossaryEntry(source="line 1", target="LINIO 1"),
        GlossaryEntry(source="line 2", target="[T] line 2"),
    ]
    assert ws.glossary_violations(entries) == [
        {"id": 1, "source_term": "line 1", "expected_target": "LINIO 1"}
    ]


def test_build_tools_dispatch() -> None:
    ws = ProofreadWorkspace(make_segments())
    progressed: list[int] = []
    retranslated: list[tuple] = []

    def fake_retranslate(start_id: int, end_id: int, instruction: str) -> dict[int, str]:
        retranslated.append((start_id, end_id, instruction))
        return {i: f"nova {i}" for i in range(start_id, end_id + 1)}

    registry = build_proofread_tools(
        ws,
        [GlossaryEntry(source="line 1", target="LINIO")],
        fake_retranslate,
        lambda: progressed.append(len(ws.checked)),
    )
    assert registry.names() == [
        "check_glossary", "edit_segment", "flag_segment",
        "read_segments", "retranslate_range",
    ]

    rows = json.loads(registry.execute("read_segments", {"start_id": 1, "end_id": 2}))
    assert rows[0]["id"] == 1
    assert progressed == [2]

    assert "LINIO" in registry.execute("check_glossary", {})

    assert registry.execute(
        "edit_segment", {"id": 1, "new_target": "x", "reason": "fix"}
    ) == "ok"
    assert registry.execute("flag_segment", {"id": 2, "note": "check"}) == "ok"

    out = json.loads(
        registry.execute(
            "retranslate_range",
            {"start_id": 3, "end_id": 4, "instruction": "smoother"},
        )
    )
    assert retranslated == [(3, 4, "smoother")]
    assert ws.segments[3]["target"] == "nova 3"
    assert out == [{"id": 3, "text": "nova 3"}, {"id": 4, "text": "nova 4"}]


def run_proofread_with(
    tmp_path: Path, responses: list[str], *, glossary=None, max_rounds: int = 3
):
    meter = BudgetMeter(tmp_path, EventBus(), CoreConfig())
    provider = create_llm({"type": "scripted", "responses": responses})
    recorder = AgentRunRecorder(tmp_path / "agent-runs", "proof-test")
    progress: list[tuple[int, int]] = []
    rounds: list[int] = []
    result = run_proofread(
        make_segments(),
        ProofreadSettings(
            source_language="en", target_language="eo",
            model="test-model", max_rounds=max_rounds,
        ),
        provider,
        meter,
        glossary or [],
        load_template(tmp_path, "proofread"),
        load_template(tmp_path, "translate"),
        project="p",
        task_id="t1",
        recorder=recorder,
        emit_progress=lambda current, total: progress.append((current, total)),
        on_round=rounds.append,
    )
    return result, progress, rounds


def test_proofread_edit_and_converge(tmp_path: Path) -> None:
    responses = [
        '{"tool": "read_segments", "arguments": {"start_id": 1, "end_id": 5, "context": 0}}',
        '{"tool": "edit_segment", "arguments": {"id": 2, "new_target": "polished", "reason": "awkward"}}',
        '{"tool": "end_round", "arguments": {"summary": "one fix"}}',
        '{"tool": "read_segments", "arguments": {"start_id": 1, "end_id": 5, "context": 0}}',
        '{"done": true, "summary": "clean"}',
    ]
    result, progress, rounds = run_proofread_with(tmp_path, responses)
    assert result.converged is True
    assert result.segments[1]["target"] == "polished"
    assert result.report["reason"] == "done"
    assert result.report["rounds"] == 2
    assert result.report["edits"][0]["round"] == 1
    assert rounds == [1, 2]
    assert progress[0] == (5, 5)
    assert progress[-1] == (5, 5)


def test_proofread_retranslate_goes_through_same_meter(tmp_path: Path) -> None:
    responses = [
        '{"tool": "retranslate_range", "arguments": {"start_id": 1, "end_id": 2}}',
        '[{"id": 1, "text": "nova 1"}, {"id": 2, "text": "nova 2"}]',
        '{"done": true, "summary": "retranslated"}',
    ]
    result, _, _ = run_proofread_with(tmp_path, responses)
    assert result.segments[0]["target"] == "nova 1"
    assert result.segments[1]["target"] == "nova 2"
    assert all(e["reason"].startswith("retranslated") for e in result.report["edits"])
    ledger_lines = sum(
        len(path.read_text(encoding="utf-8").strip().splitlines())
        for path in (tmp_path / "budget").glob("ledger-*.jsonl")
    )
    assert ledger_lines == 3


def test_proofread_flags_survive_into_report(tmp_path: Path) -> None:
    responses = [
        '{"tool": "flag_segment", "arguments": {"id": 3, "note": "idiom unclear"}}',
        '{"done": true, "summary": "flagged one"}',
    ]
    result, _, _ = run_proofread_with(tmp_path, responses)
    assert result.report["flags"] == [{"id": 3, "note": "idiom unclear", "round": 1}]
