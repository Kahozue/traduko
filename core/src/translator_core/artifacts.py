"""Numbered, human-readable stage artifacts under a task directory."""
from __future__ import annotations

import json
from pathlib import Path

from .fsutil import atomic_write_text


class ArtifactStore:
    def __init__(self, task_dir: Path) -> None:
        self.dir = task_dir / "artifacts"

    def path_for(self, index: int, name: str) -> Path:
        return self.dir / f"{index:02d}-{name}"

    def exists(self, index: int, name: str) -> bool:
        return self.path_for(index, name).exists()

    def write_json(
        self, index: int, name: str, payload: dict, schema_version: int = 1
    ) -> Path:
        path = self.path_for(index, name)
        body = {"schema_version": schema_version, **payload}
        atomic_write_text(path, json.dumps(body, ensure_ascii=False, indent=2))
        return path

    def read_json(self, index: int, name: str) -> dict:
        path = self.path_for(index, name)
        data = json.loads(path.read_text(encoding="utf-8"))
        if "schema_version" not in data:
            raise ValueError(f"artifact missing schema_version: {path}")
        return data
