"""Numbered, human-readable stage artifacts under a task directory."""
from __future__ import annotations

import json
from pathlib import Path

from .fsutil import atomic_write_text


class ArtifactValidationError(ValueError):
    pass


def validate_translation_payload(payload: dict) -> None:
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ArtifactValidationError("segments must be a list")
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            raise ArtifactValidationError(f"segment {i} is not an object")
        for key, types in (
            ("id", int),
            ("start", (int, float)),
            ("end", (int, float)),
            ("source", str),
            ("target", str),
        ):
            if key not in seg or not isinstance(seg[key], types):
                raise ArtifactValidationError(
                    f"segment {i} missing or bad field: {key}"
                )


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

    def latest_path(self, name: str) -> Path:
        matches = sorted(self.dir.glob(f"*-{name}"))
        if not matches:
            raise FileNotFoundError(f"no artifact matching *-{name} in {self.dir}")
        return matches[-1]

    def read_latest_json(self, name: str) -> dict:
        path = self.latest_path(name)
        data = json.loads(path.read_text(encoding="utf-8"))
        if "schema_version" not in data:
            raise ValueError(f"artifact missing schema_version: {path}")
        return data

    def list_artifacts(self) -> list[dict]:
        if not self.dir.exists():
            return []
        items: list[dict] = []
        for path in sorted(self.dir.glob("*")):
            if not path.is_file() or path.suffix == ".tmp":
                continue
            stem = path.name
            index: int | None = None
            name = stem
            if len(stem) >= 3 and stem[:2].isdigit() and stem[2] == "-":
                index = int(stem[:2])
                name = stem[3:]
            schema_version: int | None = None
            if path.suffix == ".json":
                try:
                    schema_version = json.loads(path.read_text(encoding="utf-8")).get(
                        "schema_version"
                    )
                except (ValueError, OSError):
                    schema_version = None
            stat = path.stat()
            items.append(
                {
                    "file": stem,
                    "index": index if index is not None else 0,
                    "name": name,
                    "schema_version": schema_version,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
        return items

    def next_index_for(self, name: str) -> int:
        matches = sorted(self.dir.glob(f"*-{name}")) if self.dir.exists() else []
        if not matches:
            return 1
        return int(matches[-1].name[:2]) + 1

    def write_next_json(
        self, name: str, payload: dict, schema_version: int = 1
    ) -> Path:
        return self.write_json(self.next_index_for(name), name, payload, schema_version)

    def read_named_json(self, file: str) -> dict:
        path = self.dir / file
        data = json.loads(path.read_text(encoding="utf-8"))
        if "schema_version" not in data:
            raise ValueError(f"artifact missing schema_version: {path}")
        return data
