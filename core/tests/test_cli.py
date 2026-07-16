import json
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


def test_serve_command_exists() -> None:
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--port" in result.output
