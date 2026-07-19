import json
from pathlib import Path

from traduko.glossary import GlossaryStore
from traduko.glossary.migrate import migrate_legacy_glossaries
from traduko.workspace import Workspace


def write_legacy(path: Path, rows: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("source,target,notes,scope\n" + rows, encoding="utf-8")


def test_migrates_global_into_default_table(tmp_path: Path) -> None:
    write_legacy(
        tmp_path / "glossaries" / "global.csv",
        "Kirito,桐人,protagonist,\nAsuna,亞絲娜,,other-show\n",
    )
    migrate_legacy_glossaries(tmp_path)

    store = GlossaryStore(tmp_path)
    tables = store.list_tables()
    assert [t.id for t in tables] == ["default"]
    default = tables[0]
    assert default.name == "預設名詞表"
    assert default.domain == "general"
    assert default.enabled is True

    entries = store.read_entries("default")
    assert {e.source for e in entries} == {"Kirito", "Asuna"}
    assert all(e.category == "" for e in entries)

    assert (tmp_path / "glossaries" / "global.csv.migrated").exists()
    assert not (tmp_path / "glossaries" / "global.csv").exists()


def test_migrates_project_files_into_named_tables(tmp_path: Path) -> None:
    write_legacy(tmp_path / "glossaries" / "global.csv", "Kirito,桐人,,\n")
    write_legacy(tmp_path / "glossaries" / "novel-x.csv", "Yui,結衣,,\n")
    migrate_legacy_glossaries(tmp_path)

    store = GlossaryStore(tmp_path)
    by_name = {t.name: t for t in store.list_tables()}
    assert "預設名詞表" in by_name
    assert "novel-x 名詞表" in by_name
    novel = by_name["novel-x 名詞表"]
    assert novel.domain == "general"
    assert [e.source for e in store.read_entries(novel.id)] == ["Yui"]
    assert (tmp_path / "glossaries" / "novel-x.csv.migrated").exists()


def test_idempotent_when_manifest_exists(tmp_path: Path) -> None:
    write_legacy(tmp_path / "glossaries" / "global.csv", "Kirito,桐人,,\n")
    migrate_legacy_glossaries(tmp_path)
    # A late legacy file appears but manifest already exists: left untouched.
    write_legacy(tmp_path / "glossaries" / "late.csv", "Late,遲,,\n")
    migrate_legacy_glossaries(tmp_path)

    assert (tmp_path / "glossaries" / "late.csv").exists()
    assert not (tmp_path / "glossaries" / "late.csv.migrated").exists()
    names = {t.name for t in GlossaryStore(tmp_path).list_tables()}
    assert "late 名詞表" not in names


def test_empty_glossaries_writes_empty_manifest(tmp_path: Path) -> None:
    (tmp_path / "glossaries").mkdir(parents=True)
    migrate_legacy_glossaries(tmp_path)
    manifest = json.loads(
        (tmp_path / "glossaries" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["order"] == []
    # A second call is a no-op and does not raise.
    migrate_legacy_glossaries(tmp_path)
    assert GlossaryStore(tmp_path).list_tables() == []


def test_workspace_open_migrates_once(tmp_path: Path) -> None:
    root = tmp_path / "data"
    (root / "glossaries").mkdir(parents=True)
    (root / "glossaries" / "global.csv").write_text(
        "source,target,notes,scope\nKirito,桐人,,\n", encoding="utf-8"
    )
    ws = Workspace.open(root)
    assert [t.name for t in GlossaryStore(ws.root).list_tables()] == ["預設名詞表"]
    assert (root / "glossaries" / "global.csv.migrated").exists()
