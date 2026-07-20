import json
from pathlib import Path

import pytest

from traduko.glossary import (
    GlossaryEntry,
    GlossaryStore,
    GlossaryTableMeta,
    format_for_prompt,
    load_glossary,
    relevant_entries,
)


# --- empty root -------------------------------------------------------------


def test_empty_root_has_no_tables(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    assert store.list_tables() == []
    assert store.enabled_merged() == []
    assert load_glossary(tmp_path, "novel-x") == []


# --- create / list ----------------------------------------------------------


def test_create_table_persists_csv_and_manifest(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    meta = store.create_table("Anime Terms", "video")
    assert isinstance(meta, GlossaryTableMeta)
    assert meta.name == "Anime Terms"
    assert meta.domain == "video"
    assert meta.enabled is True
    assert (tmp_path / "glossaries" / f"{meta.id}.csv").exists()
    assert [m.id for m in store.list_tables()] == [meta.id]
    # a fresh store reads the same manifest back
    assert [m.id for m in GlossaryStore(tmp_path).list_tables()] == [meta.id]


def test_create_table_slugifies_and_dedupes_ids(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    a = store.create_table("Anime Terms", "video")
    b = store.create_table("Anime Terms", "video")
    assert a.id == "anime-terms"
    assert b.id == "anime-terms-2"


def test_create_table_cjk_name_falls_back_to_table_id(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    meta = store.create_table("預設名詞表", "general")
    assert meta.id == "table"


def test_list_tables_filters_by_domain(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    store.create_table("V", "video")
    store.create_table("D", "document")
    assert [m.domain for m in store.list_tables("video")] == ["video"]


# --- entries round-trip -----------------------------------------------------


def test_write_and_read_entries_round_trip(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    meta = store.create_table("Terms", "document")
    entries = [
        GlossaryEntry(source="Kirito", target="桐人", notes="protagonist", category="人名"),
        GlossaryEntry(source="Aincrad", target="艾恩葛朗特", category="地名"),
    ]
    store.write_entries(meta.id, entries)
    assert store.read_entries(meta.id) == entries


def test_write_entries_bumps_updated_at(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    meta = store.create_table("Terms", "general")
    store.write_entries(
        meta.id, [GlossaryEntry(source="a", target="A")], now="2030-01-01T00:00:00Z"
    )
    assert store.get_table(meta.id).updated_at == "2030-01-01T00:00:00Z"


# --- rename / enable / delete ----------------------------------------------


def test_rename_and_set_enabled(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    meta = store.create_table("Old", "general")
    assert store.rename_table(meta.id, "New").name == "New"
    assert store.set_enabled(meta.id, False).enabled is False
    assert store.get_table(meta.id).enabled is False
    assert store.get_table(meta.id).name == "New"


def test_delete_table_removes_csv_and_order(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    meta = store.create_table("Gone", "general")
    csv_path = tmp_path / "glossaries" / f"{meta.id}.csv"
    assert csv_path.exists()
    store.delete_table(meta.id)
    assert not csv_path.exists()
    assert store.list_tables() == []
    with pytest.raises(KeyError):
        store.get_table(meta.id)


def test_unknown_table_raises_key_error(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    for call in (
        lambda: store.get_table("nope"),
        lambda: store.read_entries("nope"),
        lambda: store.write_entries("nope", []),
        lambda: store.rename_table("nope", "x"),
        lambda: store.set_enabled("nope", True),
        lambda: store.delete_table("nope"),
        lambda: store.export_table("nope", "csv"),
    ):
        with pytest.raises(KeyError):
            call()


# --- enabled_merged ---------------------------------------------------------


def test_enabled_merged_respects_order_and_enabled(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    first = store.create_table("First", "general")
    second = store.create_table("Second", "general")
    store.write_entries(first.id, [GlossaryEntry(source="Kirito", target="桐人")])
    store.write_entries(
        second.id,
        [
            GlossaryEntry(source="Kirito", target="キリト"),  # loses: earlier table wins
            GlossaryEntry(source="Yui", target="結衣"),
        ],
    )
    merged = {e.source: e.target for e in store.enabled_merged()}
    assert merged == {"Kirito": "桐人", "Yui": "結衣"}
    # disabling the first table lets the second table's Kirito win
    store.set_enabled(first.id, False)
    merged2 = {e.source: e.target for e in store.enabled_merged()}
    assert merged2 == {"Kirito": "キリト", "Yui": "結衣"}


def test_enabled_merged_filters_by_domain(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    v = store.create_table("V", "video")
    d = store.create_table("D", "document")
    store.write_entries(v.id, [GlossaryEntry(source="a", target="A")])
    store.write_entries(d.id, [GlossaryEntry(source="b", target="B")])
    assert {e.source for e in store.enabled_merged("video")} == {"a"}


# --- import / export --------------------------------------------------------


def test_import_export_csv_round_trip(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    content = "source,target,notes,category\r\nKirito,桐人,hero,人名\r\n"
    meta = store.import_table("Imported", "general", content, "csv")
    assert [e.source for e in store.read_entries(meta.id)] == ["Kirito"]
    exported = store.export_table(meta.id, "csv")
    assert exported.startswith("source,target,notes,category")
    assert "Kirito" in exported


def test_import_export_json_round_trip(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    content = json.dumps(
        {"entries": [{"source": "Yui", "target": "結衣", "notes": "", "category": "人名"}]}
    )
    meta = store.import_table("Imp", "general", content, "json")
    assert store.read_entries(meta.id) == [
        GlossaryEntry(source="Yui", target="結衣", category="人名")
    ]
    exported = json.loads(store.export_table(meta.id, "json"))
    assert exported["name"] == "Imp"
    assert exported["domain"] == "general"
    assert exported["entries"][0]["source"] == "Yui"


def test_import_bare_json_array(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    content = json.dumps([{"source": "Yui", "target": "結衣"}])
    meta = store.import_table("Imp", "general", content, "json")
    assert [e.source for e in store.read_entries(meta.id)] == ["Yui"]


def test_import_skips_rows_missing_source_or_target(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    content = "source,target,notes,category\r\nKirito,桐人,,\r\n,orphan,,\r\nNoTarget,,,\r\n"
    meta = store.import_table("Imp", "general", content, "csv")
    assert [e.source for e in store.read_entries(meta.id)] == ["Kirito"]


# --- prompt helpers (behaviour unchanged from v1) ---------------------------


def test_relevant_entries_matches_substring() -> None:
    entries = [
        GlossaryEntry(source="Kirito", target="桐人"),
        GlossaryEntry(source="Aincrad", target="艾恩葛朗特"),
    ]
    hits = relevant_entries(entries, ["Kirito draws his sword.", "Nothing here."])
    assert [e.source for e in hits] == ["Kirito"]


def test_format_for_prompt() -> None:
    assert format_for_prompt([]) == "(none)"
    text = format_for_prompt(
        [GlossaryEntry(source="Kirito", target="桐人", notes="protagonist")]
    )
    assert text == "Kirito -> 桐人  (protagonist)"


# --- comic domain reserve (v3_5-10) ------------------------------------------


def test_comic_domain_tables_work_end_to_end(tmp_path: Path) -> None:
    # The comic pipeline does not exist yet, but the glossary model reserves
    # the domain: tables must create, take entries, filter, and land in a new
    # comic task's selection just like the live domains.
    from traduko.glossary import task_glossary_for_new_task

    store = GlossaryStore(tmp_path)
    meta = store.create_table("Comic terms", "comic")
    assert meta.domain == "comic"
    store.write_entries(meta.id, [GlossaryEntry(source="ネコ", target="貓")])
    assert [e.source for e in store.read_entries(meta.id)] == ["ネコ"]
    assert [m.id for m in store.list_tables(domain="comic")] == [meta.id]

    glossary = task_glossary_for_new_task(tmp_path, "comic")
    assert glossary.global_ids == [meta.id]
