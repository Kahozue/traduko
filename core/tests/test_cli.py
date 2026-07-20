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


# --- create-task apply chain (v3_5-10: CLI equals HTTP) ----------------------

SRT = "1\n00:00:00,000 --> 00:00:01,000\nhello\n"


def test_create_applies_domain_translation_defaults_and_switches(
    tmp_path: Path,
) -> None:
    # The CLI must run the same post-create apply chain as the HTTP endpoint:
    # domain translation defaults land in the translate stage, and the audio
    # domain's pipeline defaults (dub off) land as initial switches.
    from traduko.config import load_config, save_config
    from traduko.workspace import Workspace

    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    Workspace.open(tmp_path)  # seed default profiles
    config = load_config(tmp_path)
    config.translation_defaults.audio.target_language = "ja"
    save_config(tmp_path, config)
    input_file = tmp_path / "in.wav"
    input_file.write_bytes(b"fake audio")

    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "audio-dub"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    shown = runner.invoke(app, ["task", "show", task_id], env=env)
    payload = json.loads(shown.output)
    translate = next(s for s in payload["stages"] if s["type"] == "translate")
    assert translate["params"]["target_language"] == "ja"
    assert payload["switches"] is not None
    assert payload["switches"]["dub"] is False
    mix = next(s for s in payload["stages"] if s["type"] == "mix_audio")
    assert mix["status"] == "skipped"


def test_create_compose_task_with_a_transcript_file(tmp_path: Path) -> None:
    from traduko.workspace import Workspace

    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    Workspace.open(tmp_path)
    transcript = tmp_path / "lines.srt"
    transcript.write_text(SRT, encoding="utf-8")

    created = runner.invoke(
        app,
        [
            "task", "create", "--profile", "audio-compose",
            "--transcript", str(transcript),
        ],
        env=env,
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    shown = runner.invoke(app, ["task", "show", task_id], env=env)
    payload = json.loads(shown.output)
    assert payload["input_path"] == str(transcript.resolve())
    ingest = next(s for s in payload["stages"] if s["type"] == "ingest_transcript")
    assert ingest["params"]["transcript"] == {
        "kind": "file", "path": str(transcript.resolve())
    }
    # The compose exception: audio dubbing defaults to off, compose pins it on.
    assert payload["switches"]["dub"] is True


def test_create_compose_task_without_a_transcript_is_rejected(
    tmp_path: Path,
) -> None:
    from traduko.workspace import Workspace

    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    Workspace.open(tmp_path)

    result = runner.invoke(
        app, ["task", "create", "--profile", "audio-compose"], env=env
    )
    assert result.exit_code == 1
    assert "transcript" in result.output
    # A rejected create leaves nothing on disk.
    tasks_dir = tmp_path / "projects" / "default" / "tasks"
    assert not tasks_dir.exists() or not any(tasks_dir.iterdir())


# --- task switches / translate-opts (v3_5-10, deferred from v3_5-04/08) ------


def _seeded_env(tmp_path: Path) -> dict[str, str]:
    from traduko.workspace import Workspace

    Workspace.open(tmp_path)
    return {"TRADUKO_DATA_ROOT": str(tmp_path)}


def _create_audio_dub_task(tmp_path: Path, env: dict[str, str]) -> str:
    input_file = tmp_path / "in.wav"
    input_file.write_bytes(b"fake audio")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "audio-dub"], env=env
    )
    assert created.exit_code == 0, created.output
    return created.output.strip().splitlines()[-1]


def _show_task(task_id: str, env: dict[str, str]) -> dict:
    shown = runner.invoke(app, ["task", "show", task_id], env=env)
    return json.loads(shown.output)


def test_task_switches_prints_current_values(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    task_id = _create_audio_dub_task(tmp_path, env)

    result = runner.invoke(app, ["task", "switches", task_id], env=env)
    assert result.exit_code == 0, result.output
    assert "translate: True" in result.output
    assert "dub: False" in result.output


def test_task_switches_disables_the_dub_group(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"fake video")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "av-dub"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    result = runner.invoke(app, ["task", "switches", task_id, "--no-dub"], env=env)
    assert result.exit_code == 0, result.output
    assert "dub: False" in result.output
    payload = _show_task(task_id, env)
    mix = next(s for s in payload["stages"] if s["type"] == "mix_audio")
    assert mix["status"] == "skipped"


def test_task_switches_diarize_on_inserts_the_stage_from_the_cli(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    input_file = tmp_path / "talk.mp3"
    input_file.write_bytes(b"fake audio")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "audio-transcribe"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    result = runner.invoke(app, ["task", "switches", task_id, "--diarize"], env=env)
    assert result.exit_code == 0, result.output
    types = [s["type"] for s in _show_task(task_id, env)["stages"]]
    assert types == ["extract_audio", "asr", "diarize", "export_transcript"]


def test_task_switches_diarize_rejects_a_task_with_no_transcription(
    tmp_path: Path,
) -> None:
    env = _seeded_env(tmp_path)
    input_file = tmp_path / "lines.srt"
    input_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n", encoding="utf-8")
    created = runner.invoke(
        app,
        ["task", "create", str(input_file), "--profile", "subtitle-translate"],
        env=env,
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    result = runner.invoke(app, ["task", "switches", task_id, "--diarize"], env=env)
    assert result.exit_code == 1
    assert "transcription" in result.output


def test_task_switches_rejects_a_running_task(tmp_path: Path) -> None:
    from traduko.models import TaskStatus
    from traduko.workspace import Workspace

    env = _seeded_env(tmp_path)
    task_id = _create_audio_dub_task(tmp_path, env)
    ws = Workspace.open(tmp_path)
    record = ws.store.load("default", task_id)
    record.status = TaskStatus.RUNNING
    ws.store.save(record)

    result = runner.invoke(app, ["task", "switches", task_id, "--no-dub"], env=env)
    assert result.exit_code == 1
    assert "running" in result.output


def test_task_translate_opts_prints_current_values(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    task_id = _create_audio_dub_task(tmp_path, env)

    result = runner.invoke(app, ["task", "translate-opts", task_id], env=env)
    assert result.exit_code == 0, result.output
    assert "target_language:" in result.output


def test_task_translate_opts_updates_target_language(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    task_id = _create_audio_dub_task(tmp_path, env)

    result = runner.invoke(
        app,
        ["task", "translate-opts", task_id, "--target-language", "ja"],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "target_language: ja" in result.output
    payload = _show_task(task_id, env)
    translate = next(s for s in payload["stages"] if s["type"] == "translate")
    assert translate["params"]["target_language"] == "ja"


def test_task_translate_opts_rejects_a_running_task(tmp_path: Path) -> None:
    from traduko.models import TaskStatus
    from traduko.workspace import Workspace

    env = _seeded_env(tmp_path)
    task_id = _create_audio_dub_task(tmp_path, env)
    ws = Workspace.open(tmp_path)
    record = ws.store.load("default", task_id)
    record.status = TaskStatus.RUNNING
    ws.store.save(record)

    result = runner.invoke(
        app,
        ["task", "translate-opts", task_id, "--target-language", "ja"],
        env=env,
    )
    assert result.exit_code == 1
    assert "running" in result.output


# --- task dub-params / export (v3_5-10, deferred from v3_5-06/07) ------------


def _create_av_dub_task(tmp_path: Path, env: dict[str, str]) -> str:
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"fake video")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "av-dub"], env=env
    )
    assert created.exit_code == 0, created.output
    return created.output.strip().splitlines()[-1]


def test_task_dub_params_prints_current_values(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    task_id = _create_av_dub_task(tmp_path, env)

    result = runner.invoke(app, ["task", "dub-params", task_id], env=env)
    assert result.exit_code == 0, result.output
    assert "voice_mode: clone" in result.output
    assert "dub_text: auto" in result.output


def test_task_dub_params_writes_to_the_dub_stages(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    task_id = _create_av_dub_task(tmp_path, env)

    result = runner.invoke(
        app,
        [
            "task", "dub-params", task_id,
            "--voice-mode", "design",
            "--instruction", "a calm low voice",
            "--dub-text", "original",
        ],
        env=env,
    )
    assert result.exit_code == 0, result.output
    assert "voice_mode: design" in result.output
    payload = _show_task(task_id, env)
    tts = next(s for s in payload["stages"] if s["type"] == "tts_synthesize")
    assert tts["params"]["voice_mode"] == "design"
    assert tts["params"]["voice_instruction"] == "a calm low voice"
    assert tts["params"]["dub_text"] == "original"
    diarize = next(s for s in payload["stages"] if s["type"] == "diarize")
    assert diarize["params"]["voice_mode"] == "design"


def test_task_dub_params_rejects_an_unknown_engine(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    task_id = _create_av_dub_task(tmp_path, env)

    result = runner.invoke(
        app, ["task", "dub-params", task_id, "--engine-id", "nope"], env=env
    )
    assert result.exit_code == 1
    assert "nope" in result.output


def _completed_task(tmp_path: Path, env: dict[str, str], input_name: str) -> str:
    profile_dir = tmp_path / "profiles"
    if not (profile_dir / "passthrough.yaml").exists():
        (profile_dir / "passthrough.yaml").write_text(
            "schema_version: 1\nname: passthrough\nstages:\n  - type: noop\n",
            encoding="utf-8",
        )
    input_file = tmp_path / input_name
    input_file.write_bytes(b"fake bytes")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "passthrough"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]
    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    return task_id


def test_task_export_refuses_a_dub_source_with_no_dub_mix(tmp_path: Path) -> None:
    # An audio export with source=dub on a task that never dubbed is turned
    # away at request time with a readable reason, instead of appending a
    # stage that is certain to fail once the queue reaches it.
    env = _seeded_env(tmp_path)
    task_id = _completed_task(tmp_path, env, "in.wav")

    result = runner.invoke(
        app,
        ["task", "export", task_id, "--kind", "audio", "--source", "dub"],
        env=env,
    )
    assert result.exit_code == 1
    assert "no dub mix" in result.output
    types = [s["type"] for s in _show_task(task_id, env)["stages"]]
    assert "export_audio_custom" not in types


def test_task_export_warns_about_the_pending_stages_it_will_run_first(
    tmp_path: Path,
) -> None:
    # Running the whole pending pipeline is the documented behavior, but
    # "export" reads like "just export", so say what is about to happen.
    env = _seeded_env(tmp_path)
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"fake video")
    created = runner.invoke(
        app, ["task", "create", str(input_file), "--profile", "av-default"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    result = runner.invoke(
        app, ["task", "export", task_id, "--kind", "video"], env=env
    )

    assert "will first run" in result.output
    pending = sum(
        1 for s in _show_task(task_id, env)["stages"] if s["type"] != "export_video"
    )
    assert str(pending) in result.output


def test_task_export_of_a_finished_task_warns_about_nothing(tmp_path: Path) -> None:
    env = _seeded_env(tmp_path)
    task_id = _completed_task(tmp_path, env, "clip.mp4")

    result = runner.invoke(
        app, ["task", "export", task_id, "--kind", "video"], env=env
    )

    assert "will first run" not in result.output


def test_task_export_refuses_when_the_disk_is_too_full(
    tmp_path: Path, monkeypatch
) -> None:
    # The space check lives in the core, so the CLI is guarded too, not just
    # the GUI's estimate call.
    env = _seeded_env(tmp_path)
    task_id = _completed_task(tmp_path, env, "clip.mp4")
    monkeypatch.setattr("traduko.tasks.check_disk_space", lambda d, need: (False, 1024))

    result = runner.invoke(
        app, ["task", "export", task_id, "--kind", "video"], env=env
    )

    assert result.exit_code == 1
    assert "disk space" in result.output
    types = [s["type"] for s in _show_task(task_id, env)["stages"]]
    assert "export_video" not in types


def test_task_export_rejects_video_export_for_a_non_video_input(
    tmp_path: Path,
) -> None:
    env = _seeded_env(tmp_path)
    task_id = _completed_task(tmp_path, env, "in.wav")

    result = runner.invoke(
        app, ["task", "export", task_id, "--kind", "video"], env=env
    )
    assert result.exit_code == 1
    assert "no video to export" in result.output


def test_task_export_rejects_original_source_for_a_non_media_input(
    tmp_path: Path,
) -> None:
    env = _seeded_env(tmp_path)
    task_id = _completed_task(tmp_path, env, "in.srt")

    result = runner.invoke(
        app,
        ["task", "export", task_id, "--kind", "audio", "--source", "original"],
        env=env,
    )
    assert result.exit_code == 1
    assert "original audio source needs a media input" in result.output
