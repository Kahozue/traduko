from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from traduko.config import (
    CoreConfig,
    DiscordBotConfig,
    McpServerConfig,
    SkillConfig,
    load_config,
    save_config,
)


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


def test_mcp_servers_round_trip(tmp_path: Path) -> None:
    config = CoreConfig.model_validate(
        {
            "mcp_servers": {
                "files": {
                    "transport": "stdio",
                    "command": "uvx",
                    "args": ["mcp-server-files"],
                    "enabled": True,
                },
                "remote": {
                    "transport": "http",
                    "url": "http://127.0.0.1:9000/mcp",
                    "auth_token": "secret",
                },
            }
        }
    )
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    files = loaded.mcp_servers["files"]
    assert files.transport == "stdio"
    assert files.args == ["mcp-server-files"]
    assert files.enabled is True
    remote = loaded.mcp_servers["remote"]
    assert remote.transport == "http"
    assert remote.auth_token == "secret"
    assert remote.enabled is False


def test_mcp_server_defaults_and_unknown_transport() -> None:
    assert CoreConfig().mcp_servers == {}
    with pytest.raises(ValidationError):
        CoreConfig.model_validate({"mcp_servers": {"x": {"transport": "ws"}}})


def test_skills_defaults_and_round_trip(tmp_path: Path) -> None:
    assert CoreConfig().skills == {}
    fresh = SkillConfig()
    assert fresh.enabled is False
    assert fresh.confirmed is False

    config = CoreConfig.model_validate(
        {
            "skills": {
                "honorific-style": {"enabled": True, "confirmed": True, "note": "keep"},
                "draft": {},
            }
        }
    )
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    skill = loaded.skills["honorific-style"]
    assert skill.enabled is True
    assert skill.confirmed is True
    assert skill.model_dump()["note"] == "keep"
    draft = loaded.skills["draft"]
    assert draft.enabled is False
    assert draft.confirmed is False


def test_mcp_confirmed_round_trip(tmp_path: Path) -> None:
    config = CoreConfig.model_validate(
        {"mcp_servers": {"files": {"command": "uvx", "enabled": True, "confirmed": True}}}
    )
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.mcp_servers["files"].confirmed is True


def test_confirmed_migration_rules() -> None:
    # Migration lives in load_config only (see the v2-04 yaml test below).
    # Validation of API bodies and proposal patches never auto-confirms: a
    # new enabled entry without an explicit confirmed stays behind the gate.
    assert McpServerConfig.model_validate({"enabled": True}).confirmed is False
    assert SkillConfig.model_validate({"enabled": True}).confirmed is False
    assert McpServerConfig(enabled=True).confirmed is False
    assert SkillConfig(enabled=True).confirmed is False
    # An explicit confirmed value is always respected.
    assert McpServerConfig.model_validate({"enabled": True, "confirmed": True}).confirmed is True
    assert SkillConfig.model_validate({"enabled": True, "confirmed": True}).confirmed is True
    # Disabled or brand-new entries stay unconfirmed.
    assert McpServerConfig.model_validate({"enabled": False}).confirmed is False
    assert SkillConfig.model_validate({}).confirmed is False
    assert McpServerConfig().confirmed is False
    assert SkillConfig().confirmed is False


def test_disk_migration_skips_string_enabled_and_api_shapes(tmp_path: Path) -> None:
    # A pathological quoted string ("no" parses to enabled=False) must not
    # count as enabled for migration purposes: `is True` guards the check.
    path = tmp_path / "config" / "core.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        'skills:\n  odd-one:\n    enabled: "no"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.skills["odd-one"].enabled is False
    assert config.skills["odd-one"].confirmed is False


def test_v2_04_yaml_migrates_confirmed_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "config" / "core.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "mcp_servers:\n"
        "  files:\n"
        "    transport: stdio\n"
        "    command: uvx\n"
        "    enabled: true\n"
        "  dormant:\n"
        "    transport: http\n"
        "    url: http://127.0.0.1:9000/mcp\n"
        "skills:\n"
        "  legacy-style:\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.mcp_servers["files"].confirmed is True
    assert config.mcp_servers["dormant"].confirmed is False
    assert config.skills["legacy-style"].confirmed is True

    save_config(tmp_path, config)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["mcp_servers"]["files"]["confirmed"] is True
    assert data["skills"]["legacy-style"]["confirmed"] is True


def test_dubbing_config_round_trip(tmp_path: Path) -> None:
    config = CoreConfig()
    assert config.dubbing.hf_token == ""
    assert config.dubbing.python == ""
    config.dubbing.hf_token = "hf_abc"
    config.dubbing.python = "/opt/py311/bin/python"
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.dubbing.hf_token == "hf_abc"
    assert loaded.dubbing.python == "/opt/py311/bin/python"


def test_resolve_provider_name_fallbacks(tmp_path: Path) -> None:
    from traduko.config import CoreConfig, resolve_provider_name

    real = {"type": "openai_compat", "base_url": "https://x/v1"}
    # Explicit non-fake provider always wins.
    config = CoreConfig(llm_providers={"a": real})
    assert resolve_provider_name(config, "b") == "b"
    # fake/unset falls back to the sole real provider.
    assert resolve_provider_name(config, "fake") == "a"
    assert resolve_provider_name(config, None) == "a"
    # Test doubles never qualify as an implicit default.
    config = CoreConfig(llm_providers={"agent": {"type": "scripted"}})
    assert resolve_provider_name(config, "fake") == "fake"
    # Several real providers need an explicit default.
    config = CoreConfig(llm_providers={"a": real, "b": dict(real)})
    assert resolve_provider_name(config, None) == "fake"
    config.default_provider = "b"
    assert resolve_provider_name(config, "fake") == "b"


def test_asr_config_defaults_and_roundtrip(tmp_path):
    from traduko.config import AsrConfig, CoreConfig, load_config, save_config

    config = CoreConfig()
    assert config.asr.engine == "faster_whisper"
    assert config.asr.audio_engine == ""
    assert config.asr.model == "small"
    assert config.asr.zh_prompt is True
    config.asr = AsrConfig(
        engine="openai_whisper",
        audio_engine="openai_gpt4o",
        model="medium",
        cloud_api_key="sk-x",
        custom_base_url="https://groq.example/v1",
        custom_model="whisper-large-v3",
    )
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.asr.engine == "openai_whisper"
    assert loaded.asr.audio_engine == "openai_gpt4o"
    assert loaded.asr.model == "medium"
    assert loaded.asr.cloud_api_key == "sk-x"
    assert loaded.asr.custom_model == "whisper-large-v3"


def test_pipeline_default_switches_defaults_and_roundtrip(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    # Speaker separation and dubbing are opt-in in every domain; translation
    # is on where it is the point of the pipeline (audio, document) and off
    # for video, whose export stage lands source subtitles regardless.
    assert config.dubbing.diarize_enabled is False
    assert config.dubbing.dub_enabled is False
    assert config.dubbing.translate_enabled is False
    assert config.audio.diarize_enabled is False
    assert config.audio.dub_enabled is False
    assert config.audio.translate_enabled is True
    assert config.document.dub_enabled is False
    assert config.document.translate_enabled is True
    config.audio.dub_enabled = True
    config.audio.translate_enabled = False
    config.dubbing.diarize_enabled = True
    config.document.dub_enabled = True
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.audio.dub_enabled is True
    assert loaded.audio.translate_enabled is False
    assert loaded.dubbing.diarize_enabled is True
    assert loaded.document.dub_enabled is True


def test_translation_defaults_four_domains_and_roundtrip(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    for domain in ("video", "audio", "document", "comic"):
        defaults = getattr(config.translation_defaults, domain)
        assert defaults.target_language == "zh-TW"
        assert defaults.style == ""
        assert defaults.prompt_override == ""
    config.translation_defaults.video.target_language = "ja"
    config.translation_defaults.video.style = "keep it terse"
    config.translation_defaults.document.prompt_override = "custom ${target_language}"
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.translation_defaults.video.target_language == "ja"
    assert loaded.translation_defaults.video.style == "keep it terse"
    assert loaded.translation_defaults.document.prompt_override == (
        "custom ${target_language}"
    )
    assert loaded.translation_defaults.audio.target_language == "zh-TW"


def test_config_file_without_translation_defaults_reads_defaults(
    tmp_path: Path,
) -> None:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "config.yaml").write_text(
        "schema_version: 1\ndefault_project: default\n", encoding="utf-8"
    )
    loaded = load_config(tmp_path)
    assert loaded.translation_defaults.comic.target_language == "zh-TW"


def test_comic_translation_defaults_roundtrip(tmp_path: Path) -> None:
    # comic surfaces in settings only once the comic tab exists, but the
    # config field must already hold values without losing them.
    config = load_config(tmp_path)
    config.translation_defaults.comic.target_language = "ko"
    config.translation_defaults.comic.style = "casual"
    config.translation_defaults.comic.prompt_override = "comic ${target_language}"
    save_config(tmp_path, config)
    loaded = load_config(tmp_path)
    assert loaded.translation_defaults.comic.target_language == "ko"
    assert loaded.translation_defaults.comic.style == "casual"
    assert loaded.translation_defaults.comic.prompt_override == (
        "comic ${target_language}"
    )
