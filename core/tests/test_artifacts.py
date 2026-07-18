import json
from pathlib import Path

import pytest

from traduko.artifacts import (
    ArtifactStore,
    ArtifactValidationError,
    validate_translation_payload,
)


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


def test_next_index_for_increments_over_highest(tmp_path):
    store = ArtifactStore(tmp_path)
    assert store.next_index_for("translation.json") == 1
    store.write_json(5, "translation.json", {"segments": []})
    assert store.next_index_for("translation.json") == 6


def test_write_next_json_writes_higher_numbered_version(tmp_path):
    store = ArtifactStore(tmp_path)
    store.write_json(5, "translation.json", {"segments": [{"id": 1}]})
    path = store.write_next_json("translation.json", {"segments": [{"id": 2}]})
    assert path.name == "06-translation.json"
    assert store.read_latest_json("translation.json")["segments"] == [{"id": 2}]


def test_list_artifacts_reports_index_name_and_metadata(tmp_path):
    store = ArtifactStore(tmp_path)
    store.write_json(2, "asr.json", {"segments": []})
    store.write_json(5, "translation.json", {"segments": []})
    listing = store.list_artifacts()
    assert [item["file"] for item in listing] == ["02-asr.json", "05-translation.json"]
    first = listing[0]
    assert first["index"] == 2
    assert first["name"] == "asr.json"
    assert first["schema_version"] == 1
    assert first["size"] > 0
    assert first["mtime"] > 0


def test_read_named_json_reads_exact_file(tmp_path):
    store = ArtifactStore(tmp_path)
    store.write_json(5, "translation.json", {"segments": [{"id": 1}]})
    data = store.read_named_json("05-translation.json")
    assert data["segments"] == [{"id": 1}]


def test_validate_translation_payload_accepts_well_formed():
    validate_translation_payload(
        {"segments": [{"id": 1, "start": 0.0, "end": 1.0, "source": "hi", "target": "嗨"}]}
    )


def test_validate_translation_payload_rejects_missing_target():
    with pytest.raises(ArtifactValidationError):
        validate_translation_payload(
            {"segments": [{"id": 1, "start": 0.0, "end": 1.0, "source": "hi"}]}
        )


def test_validate_translation_payload_rejects_non_list_segments():
    with pytest.raises(ArtifactValidationError):
        validate_translation_payload({"segments": "nope"})


def test_list_artifacts_tolerates_list_top_level_json(tmp_path: Path) -> None:
    # Document-pipeline artifacts (qc/chunks) are top-level lists; listing
    # must not crash on them (they simply carry no schema_version).
    store = ArtifactStore(tmp_path)
    store.write_json(1, "translation.json", {"segments": []})
    store.dir.joinpath("02-qc.json").write_text(
        json.dumps([{"chunk": 1, "flag": "echo"}]), encoding="utf-8"
    )
    items = {item["file"]: item for item in store.list_artifacts()}
    assert items["02-qc.json"]["schema_version"] is None
    assert items["01-translation.json"]["schema_version"] == 1


def test_read_latest_json_accepts_list_top_level(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.dir.mkdir(parents=True)
    store.dir.joinpath("01-chunks.json").write_text(
        json.dumps([{"id": 1}]), encoding="utf-8"
    )
    assert store.read_latest_json("chunks.json") == [{"id": 1}]
    assert store.read_named_json("01-chunks.json") == [{"id": 1}]
