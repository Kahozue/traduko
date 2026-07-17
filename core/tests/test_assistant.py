import json
from pathlib import Path

import pytest

from traduko.agents.assistant import build_assistant_tools
from traduko.agents.tools import AgentTool, ToolError
from traduko.config import BudgetConfig, CoreConfig, save_config
from traduko.models import StageRecord
from traduko.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path)


def tool_map(ws: Workspace) -> dict[str, AgentTool]:
    return {tool.name: tool for tool in build_assistant_tools(ws)}


def create_task(
    ws: Workspace, *, project: str = "p", name: str = "task one", stages=None
):
    if stages is None:
        stages = [StageRecord(type="noop")]
    return ws.store.create(
        project=project,
        input_path=str((ws.root / "in.srt")),
        profile_name="x",
        stages=stages,
        name=name,
    )


def test_build_assistant_tools_returns_only_read_only_diagnostics(
    tmp_path: Path,
) -> None:
    ws = make_ws(tmp_path)
    names = sorted(tool.name for tool in build_assistant_tools(ws))
    assert names == [
        "budget_status",
        "list_tasks",
        "read_config",
        "read_logs",
        "run_preflight",
        "task_detail",
    ]


def test_list_tasks_returns_id_title_status_stages(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    record = create_task(
        ws,
        name="第一話",
        stages=[StageRecord(type="translate"), StageRecord(type="proofread")],
    )
    tools = tool_map(ws)
    result = json.loads(tools["list_tasks"].handler({}))
    assert len(result) == 1
    entry = result[0]
    assert entry["id"] == record.id
    assert entry["project"] == "p"
    assert entry["title"] == "第一話"
    assert entry["status"] == "pending"
    assert entry["stages"] == [
        {"type": "translate", "status": "pending"},
        {"type": "proofread", "status": "pending"},
    ]


def test_list_tasks_filters_by_project(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    create_task(ws, project="a", name="in-a")
    create_task(ws, project="b", name="in-b")
    tools = tool_map(ws)
    result = json.loads(tools["list_tasks"].handler({"project": "a"}))
    assert [entry["title"] for entry in result] == ["in-a"]


def test_task_detail_returns_full_record_and_recent_events(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    record = create_task(ws)
    log_dir = ws.store.task_dir("p", record.id) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    events = [
        {"ts": f"2026-01-01T00:00:0{i}", "type": "stage_progress", "data": {"i": i}}
        for i in range(3)
    ]
    with (log_dir / "events.jsonl").open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

    tools = tool_map(ws)
    result = json.loads(
        tools["task_detail"].handler({"project": "p", "task_id": record.id})
    )
    assert result["task"]["id"] == record.id
    assert result["task"]["name"] == "task one"
    assert result["recent_events"] == events


def test_task_detail_unknown_task_raises_tool_error(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    tools = tool_map(ws)
    with pytest.raises(ToolError):
        tools["task_detail"].handler({"project": "p", "task_id": "nope"})


def test_task_detail_missing_events_file_returns_empty_list(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    record = create_task(ws)
    tools = tool_map(ws)
    result = json.loads(
        tools["task_detail"].handler({"project": "p", "task_id": record.id})
    )
    assert result["recent_events"] == []


def test_budget_status_reports_usage_limits_and_task_remaining(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    save_config(tmp_path, CoreConfig(budget=BudgetConfig(task_usd_limit=5.0)))
    ws.config = CoreConfig(budget=BudgetConfig(task_usd_limit=5.0))
    record = create_task(ws)
    tools = tool_map(ws)
    result = json.loads(tools["budget_status"].handler({}))
    assert result["month_usd"] == 0.0
    assert result["task_usd_limit"] == 5.0
    assert result["monthly_usd_limit"] is None
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["task_id"] == record.id
    assert result["tasks"][0]["remaining_usd"] == 5.0


def test_read_config_redacts_secret_keys_including_nested(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    ws.config = CoreConfig.model_validate(
        {
            "llm_providers": {
                "openai": {"api_key": "sk-secret", "base_url": "https://x"},
                "custom": {"nested": {"auth_token": "tok-secret", "note": "keep"}},
            },
            "sync": {"webdav_password": "pw-secret", "webdav_username": "eric"},
        }
    )
    tools = tool_map(ws)
    result = json.loads(tools["read_config"].handler({}))
    assert result["llm_providers"]["openai"]["api_key"] == "<redacted>"
    assert result["llm_providers"]["openai"]["base_url"] == "https://x"
    assert result["llm_providers"]["custom"]["nested"]["auth_token"] == "<redacted>"
    assert result["llm_providers"]["custom"]["nested"]["note"] == "keep"
    assert result["sync"]["webdav_password"] == "<redacted>"
    assert result["sync"]["webdav_username"] == "eric"


def test_read_config_leaves_empty_and_non_string_secret_values_untouched(
    tmp_path: Path,
) -> None:
    ws = make_ws(tmp_path)
    ws.config = CoreConfig.model_validate(
        {"llm_providers": {"empty": {"api_key": ""}, "numeric": {"token_count": 5}}}
    )
    tools = tool_map(ws)
    result = json.loads(tools["read_config"].handler({}))
    assert result["llm_providers"]["empty"]["api_key"] == ""
    assert result["llm_providers"]["numeric"]["token_count"] == 5


def test_read_logs_reports_clear_message_when_no_log_file(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    tools = tool_map(ws)
    result = tools["read_logs"].handler({})
    assert "no log file" in result.lower()
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(result)


def test_read_logs_tails_default_50_lines(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    log_dir = ws.root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "core.log").write_text(
        "\n".join(f"line {i}" for i in range(100)) + "\n", encoding="utf-8"
    )
    tools = tool_map(ws)
    result = json.loads(tools["read_logs"].handler({}))
    assert len(result) == 50
    assert result[0] == "line 50"
    assert result[-1] == "line 99"


def test_read_logs_clamps_to_500_max(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    log_dir = ws.root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "core.log").write_text(
        "\n".join(f"line {i}" for i in range(600)) + "\n", encoding="utf-8"
    )
    tools = tool_map(ws)
    result = json.loads(tools["read_logs"].handler({"lines": 10000}))
    assert len(result) == 500


def test_read_logs_clamps_below_1_to_1(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    log_dir = ws.root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "core.log").write_text("only line\n", encoding="utf-8")
    tools = tool_map(ws)
    result = json.loads(tools["read_logs"].handler({"lines": 0}))
    assert result == ["only line"]


def test_run_preflight_reports_ok_and_checks(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    input_path = tmp_path / "in.srt"
    input_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    record = ws.store.create(
        project="p",
        input_path=str(input_path),
        profile_name="x",
        stages=[StageRecord(type="noop")],
        name="task",
    )
    tools = tool_map(ws)
    result = json.loads(
        tools["run_preflight"].handler({"project": "p", "task_id": record.id})
    )
    assert result["ok"] is True
    assert any(check["name"] == "input" for check in result["checks"])
    assert any(check["name"] == "budget" for check in result["checks"])


def test_run_preflight_reports_failure_for_missing_input(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    record = ws.store.create(
        project="p",
        input_path=str(tmp_path / "missing.srt"),
        profile_name="x",
        stages=[StageRecord(type="noop")],
        name="task",
    )
    tools = tool_map(ws)
    result = json.loads(
        tools["run_preflight"].handler({"project": "p", "task_id": record.id})
    )
    assert result["ok"] is False
    assert any(
        check["name"] == "input" and check["level"] == "fail"
        for check in result["checks"]
    )


def test_run_preflight_unknown_task_raises_tool_error(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    tools = tool_map(ws)
    with pytest.raises(ToolError):
        tools["run_preflight"].handler({"project": "p", "task_id": "nope"})


def test_unexpected_exception_is_converted_to_tool_error(
    tmp_path: Path, monkeypatch
) -> None:
    ws = make_ws(tmp_path)
    record = create_task(ws)

    def boom(project: str, task_id: str):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(ws.store, "load", boom)
    tools = tool_map(ws)
    with pytest.raises(ToolError):
        tools["task_detail"].handler({"project": "p", "task_id": record.id})
