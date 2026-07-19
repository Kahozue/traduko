import json
import re
from pathlib import Path

from typer.testing import CliRunner

from traduko.cli import app

runner = CliRunner()


def setup_workspace(tmp_path: Path) -> dict[str, str]:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "passthrough.yaml").write_text(
        "schema_version: 1\nname: passthrough\nstages:\n  - type: noop\n",
        encoding="utf-8",
    )
    return {"TRADUKO_DATA_ROOT": str(tmp_path)}


def test_create_run_list_show(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    input_file = tmp_path / "in.srt"
    input_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")

    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "passthrough"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output

    listed = runner.invoke(app, ["task", "list"], env=env)
    assert task_id in listed.output
    assert "completed" in listed.output

    shown = runner.invoke(app, ["task", "show", task_id], env=env)
    payload = json.loads(shown.output)
    assert payload["status"] == "completed"


def test_create_rejects_missing_input(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    result = runner.invoke(
        app, ["task", "create", str(tmp_path / "nope.srt"), "--profile", "passthrough"],
        env=env,
    )
    assert result.exit_code != 0


def test_preflight_command_reports_ok(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    input_file = tmp_path / "in.srt"
    input_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "passthrough"], env=env
    )
    task_id = created.output.strip().splitlines()[-1]

    result = runner.invoke(app, ["task", "preflight", task_id], env=env)
    assert result.exit_code == 0, result.output
    assert "[ok] input" in result.output
    assert "[ok] budget: uncapped" in result.output


def test_run_gates_on_preflight_failure(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    input_file = tmp_path / "in.srt"
    input_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "passthrough"], env=env
    )
    task_id = created.output.strip().splitlines()[-1]
    input_file.unlink()

    pre = runner.invoke(app, ["task", "preflight", task_id], env=env)
    assert pre.exit_code == 1
    assert "[fail] input" in pre.output

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 1
    assert "preflight failed" in ran.output
    shown = runner.invoke(app, ["task", "show", task_id], env=env)
    assert json.loads(shown.output)["status"] == "pending"

    forced = runner.invoke(
        app, ["task", "run", task_id, "--skip-preflight"], env=env
    )
    assert forced.exit_code == 0, forced.output
    assert "completed" in forced.output


def _create_and_complete(tmp_path: Path, env: dict[str, str]) -> str:
    input_file = tmp_path / "in.srt"
    input_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "passthrough"], env=env
    )
    task_id = created.output.strip().splitlines()[-1]
    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output
    return task_id


def test_rerun_completed_task(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    task_id = _create_and_complete(tmp_path, env)

    reran = runner.invoke(app, ["task", "rerun", task_id], env=env)
    assert reran.exit_code == 0, reran.output
    assert "completed" in reran.output
    shown = runner.invoke(app, ["task", "show", task_id], env=env)
    assert json.loads(shown.output)["status"] == "completed"


def test_rerun_rejects_non_completed_task(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    input_file = tmp_path / "in.srt"
    input_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "passthrough"], env=env
    )
    task_id = created.output.strip().splitlines()[-1]

    reran = runner.invoke(app, ["task", "rerun", task_id], env=env)
    assert reran.exit_code == 1
    assert "pending" in reran.output


def test_rerun_gates_on_preflight_then_skip(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    task_id = _create_and_complete(tmp_path, env)
    (tmp_path / "in.srt").unlink()

    reran = runner.invoke(app, ["task", "rerun", task_id], env=env)
    assert reran.exit_code == 1
    assert "preflight failed" in reran.output
    # A failed rerun preflight leaves the completed task untouched.
    shown = runner.invoke(app, ["task", "show", task_id], env=env)
    assert json.loads(shown.output)["status"] == "completed"

    forced = runner.invoke(
        app, ["task", "rerun", task_id, "--skip-preflight"], env=env
    )
    assert forced.exit_code == 0, forced.output
    assert "completed" in forced.output


def test_serve_command_exists() -> None:
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--port" in plain
    assert "--parent-pid" in plain


class _FakeWatchdog:
    calls: list[object] = []

    def __init__(self, parent_pid: int, **_kwargs: object) -> None:
        _FakeWatchdog.calls.append(parent_pid)

    def start(self) -> None:
        _FakeWatchdog.calls.append("started")

    def stop(self) -> None:
        _FakeWatchdog.calls.append("stopped")


def _invoke_serve(monkeypatch, tmp_path: Path, args: list[str], env: dict[str, str]):
    import uvicorn

    _FakeWatchdog.calls = []
    monkeypatch.setattr("traduko.service.parentwatch.ParentWatchdog", _FakeWatchdog)
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    return runner.invoke(app, ["serve", *args], env={**setup_workspace(tmp_path), **env})


def test_serve_wires_parent_watchdog_from_flag(monkeypatch, tmp_path: Path) -> None:
    result = _invoke_serve(monkeypatch, tmp_path, ["--parent-pid", "4242"], {})
    assert result.exit_code == 0, result.output
    assert _FakeWatchdog.calls == [4242, "started", "stopped"]


def test_serve_wires_parent_watchdog_from_env(monkeypatch, tmp_path: Path) -> None:
    result = _invoke_serve(monkeypatch, tmp_path, [], {"TRADUKO_PARENT_PID": "777"})
    assert result.exit_code == 0, result.output
    assert _FakeWatchdog.calls == [777, "started", "stopped"]


def test_serve_without_parent_pid_starts_no_watchdog(monkeypatch, tmp_path: Path) -> None:
    result = _invoke_serve(monkeypatch, tmp_path, [], {})
    assert result.exit_code == 0, result.output
    assert _FakeWatchdog.calls == []


def test_sync_command_runs_and_reports(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    env = {"TRADUKO_DATA_ROOT": str(data_root)}
    (data_root / "config").mkdir(parents=True)
    (data_root / "config" / "core.yaml").write_text(
        "sync:\n"
        "  enabled: true\n"
        "  mode: folder\n"
        f"  folder_path: {tmp_path / 'cloud'}\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["sync"], env=env)
    assert result.exit_code == 0, result.output
    assert "pushed:" in result.output
    assert "conflicts: 0" in result.output
    assert (tmp_path / "cloud" / "prompts" / "translate.txt").exists()


def test_sync_command_fails_when_disabled(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    result = runner.invoke(app, ["sync"], env=env)
    assert result.exit_code == 1
    assert "not enabled" in result.output


# --- glossary subcommands (v3_5-02) ----------------------------------------


def _import_glossary(env: dict[str, str], tmp_path: Path) -> str:
    csv_file = tmp_path / "terms.csv"
    csv_file.write_text(
        "source,target,notes,category\nKirito,桐人,hero,人名\n", encoding="utf-8"
    )
    imported = runner.invoke(app, ["glossary", "import", str(csv_file)], env=env)
    assert imported.exit_code == 0, imported.output
    return imported.output.strip().splitlines()[-1]


def test_glossary_import_list_show(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    table_id = _import_glossary(env, tmp_path)

    listed = runner.invoke(app, ["glossary", "list"], env=env)
    assert listed.exit_code == 0
    assert table_id in listed.output
    assert "terms" in listed.output
    assert "Kirito" not in listed.output  # list does not dump entries

    shown = runner.invoke(app, ["glossary", "show", table_id], env=env)
    assert "Kirito -> 桐人" in shown.output
    assert "(hero)" in shown.output
    assert "#人名" in shown.output


def test_glossary_enable_disable_toggles_state(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    table_id = _import_glossary(env, tmp_path)

    runner.invoke(app, ["glossary", "disable", table_id], env=env)
    assert "disabled" in runner.invoke(app, ["glossary", "list"], env=env).output

    runner.invoke(app, ["glossary", "enable", table_id], env=env)
    out = runner.invoke(app, ["glossary", "list"], env=env).output
    assert "enabled" in out and "disabled" not in out


def test_glossary_import_json_with_name_and_domain(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    json_file = tmp_path / "g.json"
    json_file.write_text(
        json.dumps({"entries": [{"source": "Yui", "target": "結衣"}]}), encoding="utf-8"
    )
    imported = runner.invoke(
        app,
        ["glossary", "import", str(json_file), "--name", "My Terms", "--domain", "document"],
        env=env,
    )
    assert imported.exit_code == 0, imported.output
    listed = runner.invoke(app, ["glossary", "list"], env=env).output
    assert "My Terms" in listed
    assert "document" in listed


def test_glossary_export_to_stdout_and_file(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    table_id = _import_glossary(env, tmp_path)

    printed = runner.invoke(app, ["glossary", "export", table_id], env=env)
    assert "Kirito" in printed.output

    out_file = tmp_path / "out.json"
    written = runner.invoke(
        app,
        ["glossary", "export", table_id, "--format", "json", "--out", str(out_file)],
        env=env,
    )
    assert written.exit_code == 0
    assert "Kirito" in out_file.read_text(encoding="utf-8")


def test_glossary_unknown_id_exits_nonzero(tmp_path: Path) -> None:
    env = setup_workspace(tmp_path)
    for cmd in (
        ["glossary", "show", "nope"],
        ["glossary", "enable", "nope"],
        ["glossary", "disable", "nope"],
        ["glossary", "export", "nope"],
    ):
        result = runner.invoke(app, cmd, env=env)
        assert result.exit_code == 1, cmd


# --- task glossary subcommands (v3_5-03) -----------------------------------


def _setup_reapply_workspace(tmp_path: Path) -> tuple[dict[str, str], str]:
    """Create a workspace with an ASR profile and a completed task."""
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "asr-sub.yaml").write_text(
        "schema_version: 1\nname: asr-sub\nkind: video\nstages:\n"
        "  - type: extract_audio\n  - type: asr\n"
        "    params:\n      engine: faster_whisper\n"
        "  - type: segment\n  - type: translate\n"
        "    params:\n      provider: fake\n      target_language: en\n",
        encoding="utf-8",
    )
    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    input_file = tmp_path / "in.srt"
    input_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "asr-sub"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]
    return env, task_id


def test_task_glossary_shows_config(tmp_path: Path) -> None:
    env, task_id = _setup_reapply_workspace(tmp_path)
    result = runner.invoke(app, ["task", "glossary", task_id], env=env)
    assert result.exit_code == 0, result.output
    assert "asr_mode:" in result.output


def test_task_glossary_set_updates_config(tmp_path: Path) -> None:
    env, task_id = _setup_reapply_workspace(tmp_path)
    result = runner.invoke(
        app,
        ["task", "glossary-set", task_id, "--asr-mode", "force", "--use-task"],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "asr_mode: force" in result.output
    assert "use_task: True" in result.output


def test_task_glossary_set_rejects_unknown_id(tmp_path: Path) -> None:
    env, task_id = _setup_reapply_workspace(tmp_path)
    result = runner.invoke(
        app,
        ["task", "glossary-set", task_id, "--global-ids", "nope"],
        env=env,
    )
    assert result.exit_code == 1
    assert "unknown" in result.output


def test_task_glossary_set_rejects_invalid_asr_mode(tmp_path: Path) -> None:
    env, task_id = _setup_reapply_workspace(tmp_path)
    result = runner.invoke(
        app,
        ["task", "glossary-set", task_id, "--asr-mode", "bogus"],
        env=env,
    )
    assert result.exit_code == 1
