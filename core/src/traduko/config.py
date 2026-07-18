from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .fsutil import atomic_write_text

CONFIG_FILE = "config/core.yaml"


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_usd_limit: float | None = None
    monthly_usd_limit: float | None = None


class NotificationsConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    channels: list[dict] = Field(default_factory=list)


class DiscordBotConfig(BaseModel):
    """Interactive bot settings. Snowflake ids are stored as strings end to
    end: they exceed JavaScript's safe-integer range, so JSON numbers would
    silently corrupt when the desktop app round-trips the config."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    bot_token: str = ""
    bot_token_env: str = ""
    guild_id: str = ""
    channel_id: str = ""
    allowed_user_ids: list[str] = Field(default_factory=list)

    @field_validator("guild_id", "channel_id", mode="before")
    @classmethod
    def _id_to_str(cls, value: object) -> str:
        return "" if value is None else str(value)

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _ids_to_str(cls, value: object) -> list[str]:
        if value is None:
            return []
        return [str(item) for item in value]

    def resolve_token(self) -> str:
        if self.bot_token:
            return self.bot_token
        if self.bot_token_env:
            return os.environ.get(self.bot_token_env, "")
        return ""


class SyncConfig(BaseModel):
    """Cloud sync settings (design doc section 9). The target is always
    "a folder": either a local directory (which may itself be a Dropbox,
    Google Drive or iCloud synced folder) or a WebDAV collection."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    mode: Literal["folder", "webdav"] = "folder"
    folder_path: str = ""
    webdav_url: str = ""
    webdav_username: str = ""
    webdav_password: str = ""
    auto_interval_minutes: int = 0


class McpServerConfig(BaseModel):
    """One external MCP server. stdio spawns a local command; http talks
    Streamable HTTP, with an optional OAuth bearer token. `confirmed` is the
    safety gate: an enabled server only enters the agent after the user has
    reviewed its tools once."""

    model_config = ConfigDict(extra="allow")

    transport: Literal["stdio", "http"] = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    auth_token: str = ""
    enabled: bool = False
    confirmed: bool = False


class SkillConfig(BaseModel):
    """Per-skill settings, keyed by skill name (= data/skills/<name>/).
    `confirmed` is the safety gate: an enabled skill only enters the agent
    after the user has reviewed its SKILL.md once."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    confirmed: bool = False


class DubbingConfig(BaseModel):
    """Dubbing engine settings. hf_token unlocks the gated pyannote
    diarization model; python overrides interpreter discovery for the
    engine venv (VoxCPM needs >=3.10 <3.13)."""

    model_config = ConfigDict(extra="allow")

    hf_token: str = ""
    python: str = ""


class PdfEngineConfig(BaseModel):
    """PDF translation engine settings. python overrides interpreter
    discovery for the engine venv (pdf2zh-next needs >=3.10 <3.14)."""

    model_config = ConfigDict(extra="allow")

    python: str = ""


class AsrConfig(BaseModel):
    """Speech-recognition engine defaults. `engine` is the video domain's
    default engine id; `audio_engine` the audio domain's (empty = follow
    `engine`). Cloud credentials are shared by the OpenAI engine entries;
    the custom entry carries its own endpoint."""

    model_config = ConfigDict(extra="allow")

    engine: str = "faster_whisper"
    audio_engine: str = ""
    # faster-whisper model size (also the settings download target).
    model: str = "small"
    # macOS native: BCP-47 locale; empty means follow the task language.
    macos_locale: str = ""
    cloud_base_url: str = "https://api.openai.com/v1"
    cloud_api_key: str = ""
    cloud_api_key_env: str = ""
    custom_base_url: str = ""
    custom_api_key: str = ""
    custom_api_key_env: str = ""
    custom_model: str = ""
    # Bias whisper-1 / gpt-4o transcription toward Traditional Chinese
    # output on Chinese audio via the documented prompt parameter.
    zh_prompt: bool = True


class CoreConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    default_project: str = "default"
    default_provider: str = ""
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    llm_providers: dict[str, dict] = Field(default_factory=dict)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    discord_bot: DiscordBotConfig = Field(default_factory=DiscordBotConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    skills: dict[str, SkillConfig] = Field(default_factory=dict)
    dubbing: DubbingConfig = Field(default_factory=DubbingConfig)
    pdf: PdfEngineConfig = Field(default_factory=PdfEngineConfig)
    asr: AsrConfig = Field(default_factory=AsrConfig)


def _migrate_confirmed(data: dict) -> None:
    """v2-04 files predate the `confirmed` safety-gate field: entries that
    were already enabled are treated as confirmed, so upgrading does not
    silently unmount servers the user had running. This runs only on the
    raw dict read from disk; API bodies and proposal patches never migrate,
    so a new enabled entry without an explicit confirmed field stays behind
    the gate."""
    for section in ("mcp_servers", "skills"):
        entries = data.get(section)
        if not isinstance(entries, dict):
            continue
        for entry in entries.values():
            if (
                isinstance(entry, dict)
                and entry.get("enabled") is True
                and "confirmed" not in entry
            ):
                entry["confirmed"] = True


_REAL_PROVIDER_TYPES = {"openai_compat", "anthropic", "gemini"}


def real_provider_candidates(config: CoreConfig) -> list[str]:
    """Names of llm_providers entries that are real chat endpoints (the only
    kinds the GUI creates). Test doubles like scripted/fake never qualify as
    an implicit default."""
    return [
        name
        for name, entry in config.llm_providers.items()
        if isinstance(entry, dict) and entry.get("type") in _REAL_PROVIDER_TYPES
    ]


def resolve_provider_name(config: CoreConfig, requested: str | None) -> str:
    """Effective llm provider for a pipeline stage. An explicit provider other
    than "fake" wins; "fake" or unset falls back to default_provider, then to
    the sole real configured provider, so profiles seeded with provider: fake
    pick up whatever the user configured in settings without editing YAML."""
    if requested and requested != "fake":
        return requested
    default = config.default_provider
    if default and default in config.llm_providers:
        return default
    if not default:
        candidates = real_provider_candidates(config)
        if len(candidates) == 1:
            return candidates[0]
    return "fake"


def load_config(root: Path) -> CoreConfig:
    path = root / CONFIG_FILE
    if not path.exists():
        return CoreConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        _migrate_confirmed(data)
    return CoreConfig.model_validate(data)


def save_config(root: Path, config: CoreConfig) -> None:
    atomic_write_text(
        root / CONFIG_FILE,
        yaml.safe_dump(config.model_dump(), sort_keys=True, allow_unicode=True),
    )
