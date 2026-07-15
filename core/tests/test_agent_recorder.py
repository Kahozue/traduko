import json
from pathlib import Path

from traduko.agents.recorder import AgentRunRecorder


def test_records_jsonl_lines(tmp_path: Path) -> None:
    recorder = AgentRunRecorder(tmp_path / "agent-runs", "05-proofread-x")
    recorder.record(
        "turn", round=1, turn=1, tool="read_segments",
        arguments={"start_id": 1}, result="[]",
    )
    recorder.record("summary", converged=True, reason="done")
    lines = (
        (tmp_path / "agent-runs" / "05-proofread-x.jsonl")
        .read_text(encoding="utf-8").strip().splitlines()
    )
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["kind"] == "turn" and first["tool"] == "read_segments"
    assert "ts" in first
    assert json.loads(lines[1])["converged"] is True


def test_creates_directory(tmp_path: Path) -> None:
    recorder = AgentRunRecorder(tmp_path / "missing" / "agent-runs", "r1")
    recorder.record("summary", converged=False)
    assert recorder.path.exists()
