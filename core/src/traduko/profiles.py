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


# Stage types that identify a profile's task domain. Classification is
# best-effort and used only to group the new-task buttons by kind; a profile
# with no recognized marker falls back to "video" (the v1 default domain).
_DOCUMENT_STAGES = {"ingest_document", "chunk", "translate_chunks", "export_document"}
_COMIC_STAGES = {"ingest_comic", "bubble_detect", "ocr", "inpaint", "typeset"}


def profile_kind(profile: Profile) -> str:
    types = {stage.type for stage in profile.stages}
    if types & _COMIC_STAGES:
        return "comic"
    if types & _DOCUMENT_STAGES:
        return "document"
    return "video"


def list_profiles_detailed(root: Path) -> list[dict]:
    """Every profile with its inferred task kind, for the new-task picker.
    A profile that fails to parse is skipped rather than breaking the list."""
    directory = root / "profiles"
    if not directory.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            profile = load_profile(root, path.stem)
        except Exception:  # noqa: BLE001 - a malformed profile must not break the list
            continue
        rows.append({"name": path.stem, "kind": profile_kind(profile)})
    return rows
