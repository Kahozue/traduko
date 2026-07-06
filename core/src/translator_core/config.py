from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_FILE = "config/core.yaml"


class CoreConfig(BaseModel):
    schema_version: int = 1
    default_project: str = "default"


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
