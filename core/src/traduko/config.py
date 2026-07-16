from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class CoreConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    default_project: str = "default"
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    llm_providers: dict[str, dict] = Field(default_factory=dict)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    discord_bot: DiscordBotConfig = Field(default_factory=DiscordBotConfig)


def load_config(root: Path) -> CoreConfig:
    path = root / CONFIG_FILE
    if not path.exists():
        return CoreConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return CoreConfig.model_validate(data)


def save_config(root: Path, config: CoreConfig) -> None:
    path = root / CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(config.model_dump(), sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )
