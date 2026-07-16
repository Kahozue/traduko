from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from traduko.config import CoreConfig, DiscordBotConfig, load_config, save_config


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


def test_discord_bot_defaults_and_snowflakes_stay_strings(tmp_path: Path) -> None:
    path = tmp_path / "config" / "core.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "discord_bot:\n"
        "  enabled: true\n"
        "  guild_id: 123456789012345678\n"
        "  channel_id: 234567890123456789\n"
        "  allowed_user_ids: [345678901234567890]\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.discord_bot.enabled is True
    assert config.discord_bot.guild_id == "123456789012345678"
    assert config.discord_bot.channel_id == "234567890123456789"
    assert config.discord_bot.allowed_user_ids == ["345678901234567890"]

    empty = load_config(tmp_path / "nowhere")
    assert empty.discord_bot.enabled is False
    assert empty.discord_bot.allowed_user_ids == []


def test_sync_defaults_and_yaml_load(tmp_path: Path) -> None:
    empty = load_config(tmp_path)
    assert empty.sync.enabled is False
    assert empty.sync.mode == "folder"
    assert empty.sync.folder_path == ""
    assert empty.sync.webdav_url == ""
    assert empty.sync.auto_interval_minutes == 0

    path = tmp_path / "config" / "core.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "sync:\n"
        "  enabled: true\n"
        "  mode: webdav\n"
        "  webdav_url: https://dav.example.com/traduko/\n"
        "  webdav_username: kaho\n"
        "  webdav_password: secret\n"
        "  auto_interval_minutes: 15\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.sync.enabled is True
    assert config.sync.mode == "webdav"
    assert config.sync.webdav_url == "https://dav.example.com/traduko/"
    assert config.sync.webdav_username == "kaho"
    assert config.sync.webdav_password == "secret"
    assert config.sync.auto_interval_minutes == 15


def test_sync_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError):
        CoreConfig.model_validate({"sync": {"mode": "ftp"}})


def test_discord_bot_token_resolution(monkeypatch) -> None:
    direct = DiscordBotConfig(bot_token="literal", bot_token_env="TRADUKO_TEST_BOT")
    assert direct.resolve_token() == "literal"

    monkeypatch.setenv("TRADUKO_TEST_BOT", "from-env")
    via_env = DiscordBotConfig(bot_token_env="TRADUKO_TEST_BOT")
    assert via_env.resolve_token() == "from-env"

    assert DiscordBotConfig().resolve_token() == ""
