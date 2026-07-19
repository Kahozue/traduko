import json
import os
import time
from pathlib import Path

import pytest

from traduko.config import SyncConfig
from traduko.models import StageRecord
from traduko.sync.engine import (
    SyncConfigError,
    SyncEngine,
    create_target,
    list_peers,
    load_conflicts,
    machine_id,
    resolve_conflict,
)
from traduko.sync.targets import LocalFolderTarget, WebDAVTarget
from traduko.workspace import Workspace

GLOSSARY = "source,target,notes,scope\r\nterm,old,,\r\n"


def make_machine(tmp_path: Path, name: str) -> tuple[Workspace, SyncEngine]:
    ws = Workspace.open(tmp_path / name)
    engine = SyncEngine(ws.root, LocalFolderTarget(tmp_path / "remote"))
    return ws, engine


def test_machine_id_is_stable(tmp_path: Path) -> None:
    first = machine_id(tmp_path)
    assert machine_id(tmp_path) == first
    assert first


def test_first_sync_pushes_then_second_machine_pulls(tmp_path: Path) -> None:
    ws_a, engine_a = make_machine(tmp_path, "a")
    (ws_a.root / "glossaries" / "global.csv").write_text(GLOSSARY, encoding="utf-8")
    report = engine_a.run()
    assert report.ok
    assert "glossaries/global.csv" in report.pushed
    assert "prompts/translate.txt" in report.pushed

    ws_b, engine_b = make_machine(tmp_path, "b")
    report_b = engine_b.run()
    assert "glossaries/global.csv" in report_b.pulled
    # Identical seeded files hash equal on both sides, so nothing to pull.
    assert "prompts/translate.txt" not in report_b.pulled
    assert (ws_b.root / "glossaries" / "global.csv").read_bytes() == GLOSSARY.encode()


def test_second_run_is_a_noop(tmp_path: Path) -> None:
    ws_a, engine_a = make_machine(tmp_path, "a")
    engine_a.run()
    report = engine_a.run()
    assert report.pushed == [] and report.pulled == [] and report.merged == []


def test_local_edit_pushes_and_newer_remote_wins(tmp_path: Path) -> None:
    ws_a, engine_a = make_machine(tmp_path, "a")
    engine_a.run()

    prompt = ws_a.root / "prompts" / "translate.txt"
    prompt.write_text("local edit", encoding="utf-8")
    report = engine_a.run()
    assert "prompts/translate.txt" in report.pushed

    remote_prompt = tmp_path / "remote" / "prompts" / "translate.txt"
    prompt.write_text("stale local", encoding="utf-8")
    past = time.time() - 3600
    os.utime(prompt, (past, past))
    remote_prompt.write_text("fresh remote", encoding="utf-8")
    report = engine_a.run()
    assert "prompts/translate.txt" in report.pulled
    assert prompt.read_text(encoding="utf-8") == "fresh remote"


def test_glossary_conflict_surfaces_and_resolves(tmp_path: Path) -> None:
    ws_a, engine_a = make_machine(tmp_path, "a")
    (ws_a.root / "glossaries" / "global.csv").write_text(GLOSSARY, encoding="utf-8")
    engine_a.run()
    ws_b, engine_b = make_machine(tmp_path, "b")
    engine_b.run()

    (ws_a.root / "glossaries" / "global.csv").write_text(
        "source,target,notes,scope\r\nterm,mine,,\r\n", encoding="utf-8"
    )
    (ws_b.root / "glossaries" / "global.csv").write_text(
        "source,target,notes,scope\r\nterm,theirs,,\r\n", encoding="utf-8"
    )
    engine_b.run()
    report = engine_a.run()
    assert "glossaries/global.csv" in report.merged
    assert report.conflicts == 1
    conflicts = load_conflicts(ws_a.root)
    assert conflicts[0]["file"] == "glossaries/global.csv"
    assert conflicts[0]["source"] == "term"
    assert conflicts[0]["local"]["target"] == "mine"
    assert conflicts[0]["remote"]["target"] == "theirs"
    assert "term,mine" in (ws_a.root / "glossaries" / "global.csv").read_text(
        encoding="utf-8"
    )

    assert resolve_conflict(ws_a.root, "glossaries/global.csv", "term", "remote")
    assert load_conflicts(ws_a.root) == []
    assert "term,theirs" in (ws_a.root / "glossaries" / "global.csv").read_text(
        encoding="utf-8"
    )
    assert not resolve_conflict(ws_a.root, "glossaries/global.csv", "term", "remote")


def test_task_records_push_and_peers_pull(tmp_path: Path) -> None:
    ws_a, engine_a = make_machine(tmp_path, "a")
    record = ws_a.store.create(
        project="p",
        input_path="unused",
        profile_name="x",
        stages=[StageRecord(type="noop")],
        name="ep01",
    )
    engine_a.run()
    machine_a = machine_id(ws_a.root)
    remote_task = (
        tmp_path / "remote" / "tasks" / machine_a / "p" / f"{record.id}.json"
    )
    assert remote_task.exists()

    ws_b, engine_b = make_machine(tmp_path, "b")
    engine_b.run()
    peer_copy = ws_b.root / "sync" / "peers" / machine_a / "p" / f"{record.id}.json"
    assert peer_copy.exists()
    peers = list_peers(ws_b.root)
    assert len(peers) == 1
    assert peers[0]["machine"] == machine_a
    assert peers[0]["tasks"][0]["id"] == record.id
    assert peers[0]["tasks"][0]["name"] == "ep01"
    assert peers[0]["tasks"][0]["status"] == "pending"
    assert list_peers(ws_a.root) == []


def test_status_state_records_last_result(tmp_path: Path) -> None:
    ws_a, engine_a = make_machine(tmp_path, "a")
    report = engine_a.run()
    state = json.loads((ws_a.root / "sync" / "state.json").read_text(encoding="utf-8"))
    assert state["last_sync"]
    assert state["last_result"]["ok"] is True
    assert state["last_result"]["pushed"] == report.pushed


def test_create_target_validates_configuration(tmp_path: Path) -> None:
    target = create_target(SyncConfig(mode="folder", folder_path=str(tmp_path)))
    assert isinstance(target, LocalFolderTarget)
    dav = create_target(SyncConfig(mode="webdav", webdav_url="https://x/dav/"))
    assert isinstance(dav, WebDAVTarget)
    with pytest.raises(SyncConfigError):
        create_target(SyncConfig(mode="folder"))
    with pytest.raises(SyncConfigError):
        create_target(SyncConfig(mode="webdav"))


def test_manifest_two_sided_change_uses_mtime_not_merge(tmp_path: Path) -> None:
    ws_a, engine_a = make_machine(tmp_path, "a")
    engine_a.run()
    ws_b, engine_b = make_machine(tmp_path, "b")
    engine_b.run()

    def manifest(table_id: str) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "order": [table_id],
                "glossaries": {
                    table_id: {
                        "name": table_id,
                        "domain": "general",
                        "enabled": True,
                        "created_at": "2030-01-01T00:00:00Z",
                        "updated_at": "2030-01-01T00:00:00Z",
                    }
                },
            }
        )

    (ws_a.root / "glossaries" / "manifest.json").write_text(
        manifest("a"), encoding="utf-8"
    )
    (ws_b.root / "glossaries" / "manifest.json").write_text(
        manifest("b"), encoding="utf-8"
    )
    engine_b.run()
    report = engine_a.run()

    # A JSON file must never enter the row-level CSV merge.
    assert "glossaries/manifest.json" not in report.merged
    assert report.conflicts == 0
    assert "glossaries/manifest.json" in report.pushed + report.pulled


def test_glossary_csv_still_three_way_merges_category(tmp_path: Path) -> None:
    header = "source,target,notes,category\r\n"
    ws_a, engine_a = make_machine(tmp_path, "a")
    (ws_a.root / "glossaries" / "terms.csv").write_text(
        header + "term,base,,人名\r\n", encoding="utf-8"
    )
    engine_a.run()
    ws_b, engine_b = make_machine(tmp_path, "b")
    engine_b.run()

    (ws_a.root / "glossaries" / "terms.csv").write_text(
        header + "term,base,,人名\r\nkirito,桐人,,人名\r\n", encoding="utf-8"
    )
    (ws_b.root / "glossaries" / "terms.csv").write_text(
        header + "term,base,,人名\r\nyui,結衣,,人名\r\n", encoding="utf-8"
    )
    engine_b.run()
    report = engine_a.run()

    assert "glossaries/terms.csv" in report.merged
    assert report.conflicts == 0
    merged = (ws_a.root / "glossaries" / "terms.csv").read_text(encoding="utf-8")
    assert "kirito,桐人,,人名" in merged
    assert "yui,結衣,,人名" in merged
