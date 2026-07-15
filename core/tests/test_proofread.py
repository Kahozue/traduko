import json

import pytest

from traduko.agents.proofread import ProofreadWorkspace, build_proofread_tools
from traduko.agents.tools import ToolError
from traduko.glossary import GlossaryEntry


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
