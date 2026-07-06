"""Pipelines are data: a profile is an ordered list of stage declarations."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import StageRecord


class ProfileStage(BaseModel):
    type: str
    params: dict = Field(default_factory=dict)
    pause_after: bool = False


class Profile(BaseModel):
    schema_version: int = 1
    name: str
    stages: list[ProfileStage]


def load_profile(root: Path, name: str) -> Profile:
    path = root / "profiles" / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Profile.model_validate(data)


def save_profile(root: Path, profile: Profile) -> None:
    path = root / "profiles" / f"{profile.name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(profile.model_dump(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def stage_records_from(profile: Profile) -> list[StageRecord]:
    return [
        StageRecord(type=s.type, params=s.params, pause_after=s.pause_after)
        for s in profile.stages
    ]
