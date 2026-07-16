from pathlib import Path

import yaml

from traduko.config import CoreConfig, load_config, save_config


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.default_project == "default"
    assert config.schema_version == 1


def test_roundtrip(tmp_path: Path) -> None:
    save_config(tmp_path, CoreConfig(default_project="novel-x"))
    assert load_config(tmp_path).default_project == "novel-x"


def test_budget_and_providers_defaults_and_roundtrip(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.budget.task_usd_limit is None
    assert config.budget.monthly_usd_limit is None
    assert config.llm_providers == {}
    config.budget.task_usd_limit = 5.0
    config.llm_providers["local"] = {"type": "openai_compat", "base_url": "http://localhost:11434/v1"}
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.budget.task_usd_limit == 5.0
    assert loaded.llm_providers["local"]["base_url"] == "http://localhost:11434/v1"


def test_notifications_defaults_and_roundtrip(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.notifications.channels == []
    config.notifications.channels.append(
        {"type": "webhook", "url": "http://127.0.0.1:9/hook", "events": ["task_completed"]}
    )
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.notifications.channels[0]["type"] == "webhook"
    assert loaded.notifications.channels[0]["events"] == ["task_completed"]


def test_round_trip_preserves_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "config" / "core.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "schema_version: 1\n"
        "future_section:\n"
        "  key: value\n"
        "budget:\n"
        "  custom_note: hello\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    save_config(tmp_path, config)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["future_section"] == {"key": "value"}
    assert data["budget"]["custom_note"] == "hello"
