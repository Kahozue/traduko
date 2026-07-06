import json
from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore


def test_numbered_path(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    assert store.path_for(2, "asr.json") == tmp_path / "artifacts" / "02-asr.json"


def test_write_read_roundtrip_stamps_schema_version(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json(1, "asr.json", {"segments": []})
    data = store.read_json(1, "asr.json")
    assert data["schema_version"] == 1
    assert data["segments"] == []
    assert store.exists(1, "asr.json")


def test_read_rejects_missing_schema_version(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    path = store.path_for(1, "bad.json")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        store.read_json(1, "bad.json")


def test_read_latest_json(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_json(1, "segments.json", {"v": "old"})
    store.write_json(3, "segments.json", {"v": "new"})
    assert store.read_latest_json("segments.json")["v"] == "new"
    assert store.latest_path("segments.json").name == "03-segments.json"
    with pytest.raises(FileNotFoundError):
        store.read_latest_json("missing.json")
