from pathlib import Path

from traduko.glossary import GlossaryEntry, format_for_prompt, load_glossary, relevant_entries


def write_csv(path: Path, rows: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("source,target,notes,scope\n" + rows, encoding="utf-8")


def test_missing_files_return_empty(tmp_path: Path) -> None:
    assert load_glossary(tmp_path, "novel-x") == []


def test_global_scope_filtering(tmp_path: Path) -> None:
    write_csv(
        tmp_path / "glossaries" / "global.csv",
        "Kirito,桐人,protagonist,\nAsuna,亞絲娜,,other-show\n",
    )
    entries = load_glossary(tmp_path, "novel-x")
    assert [e.source for e in entries] == ["Kirito"]
    assert entries[0].notes == "protagonist"


def test_project_overrides_global(tmp_path: Path) -> None:
    write_csv(tmp_path / "glossaries" / "global.csv", "Kirito,桐人,,\n")
    write_csv(tmp_path / "glossaries" / "novel-x.csv", "Kirito,киритo,,\nYui,結衣,,\n")
    entries = {e.source: e.target for e in load_glossary(tmp_path, "novel-x")}
    assert entries == {"Kirito": "киритo", "Yui": "結衣"}


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
