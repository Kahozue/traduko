import json
from pathlib import Path

from traduko.glossary import (
    GlossaryEntry,
    GlossaryStore,
    resolve_effective_glossary,
    task_glossary_for_new_task,
)
from traduko.models import StageRecord, TaskGlossary, TaskRecord


def _task(**overrides) -> TaskRecord:
    payload = {
        "id": "task-1",
        "project": "project-1",
        "input_path": "input.mp4",
        "profile": "video",
        "stages": [StageRecord(type="translate")],
        "created_at": "2026-07-20T00:00:00+00:00",
        "updated_at": "2026-07-20T00:00:00+00:00",
    }
    payload.update(overrides)
    return TaskRecord(**payload)


def _table(
    store: GlossaryStore,
    name: str,
    domain: str,
    entries: list[GlossaryEntry],
    *,
    enabled: bool = True,
) -> str:
    meta = store.create_table(name, domain)
    store.write_entries(meta.id, entries)
    if not enabled:
        store.set_enabled(meta.id, False)
    return meta.id


def test_legacy_task_without_glossary_field_falls_back_to_all_enabled_tables(
    tmp_path: Path,
) -> None:
    store = GlossaryStore(tmp_path)
    _table(store, "General", "general", [GlossaryEntry("Kirito", "桐人")])
    _table(
        store,
        "Disabled",
        "video",
        [GlossaryEntry("Yui", "結衣")],
        enabled=False,
    )
    task = TaskRecord.model_validate_json(
        json.dumps(
            {
                "id": "legacy",
                "project": "project-1",
                "input_path": "input.mp4",
                "profile": "video",
                "stages": [],
                "created_at": "2026-07-20T00:00:00+00:00",
                "updated_at": "2026-07-20T00:00:00+00:00",
            }
        )
    )

    assert task.glossary == TaskGlossary()
    assert resolve_effective_glossary(tmp_path, task) == [
        GlossaryEntry("Kirito", "桐人")
    ]


def test_explicit_empty_glossary_configuration_disables_all_tables(
    tmp_path: Path,
) -> None:
    store = GlossaryStore(tmp_path)
    _table(store, "General", "general", [GlossaryEntry("Kirito", "桐人")])
    task = _task(glossary=TaskGlossary(global_ids=[], use_task=False))

    assert resolve_effective_glossary(tmp_path, task) == []


def test_selected_tables_follow_manifest_priority_and_skip_disabled(
    tmp_path: Path,
) -> None:
    store = GlossaryStore(tmp_path)
    first = _table(
        store,
        "First",
        "video",
        [GlossaryEntry("Kirito", "桐人"), GlossaryEntry("Asuna", "亞絲娜")],
    )
    second = _table(
        store,
        "Second",
        "general",
        [GlossaryEntry("Kirito", "キリト"), GlossaryEntry("Yui", "結衣")],
    )
    disabled = _table(
        store,
        "Disabled",
        "video",
        [GlossaryEntry("Sinon", "詩乃")],
        enabled=False,
    )
    task = _task(
        glossary=TaskGlossary(global_ids=[second, disabled, first], use_task=False)
    )

    assert {entry.source: entry.target for entry in resolve_effective_glossary(tmp_path, task)} == {
        "Kirito": "桐人",
        "Asuna": "亞絲娜",
        "Yui": "結衣",
    }


def test_task_glossary_overrides_selected_global_table(tmp_path: Path) -> None:
    store = GlossaryStore(tmp_path)
    global_id = _table(
        store,
        "Global",
        "video",
        [GlossaryEntry("Kirito", "桐人"), GlossaryEntry("Yui", "結衣")],
    )
    task = _task(glossary=TaskGlossary(global_ids=[global_id], use_task=True))
    task_csv = (
        tmp_path
        / "projects"
        / task.project
        / "tasks"
        / task.id
        / "glossary.csv"
    )
    task_csv.parent.mkdir(parents=True)
    task_csv.write_text(
        "source,target,notes,category\r\nKirito,キリト,task,人名\r\nSinon,詩乃,,人名\r\n",
        encoding="utf-8",
    )

    assert resolve_effective_glossary(tmp_path, task) == [
        GlossaryEntry("Kirito", "キリト", "task", "人名"),
        GlossaryEntry("Yui", "結衣"),
        GlossaryEntry("Sinon", "詩乃", "", "人名"),
    ]


def test_empty_global_ids_with_task_glossary_uses_only_task_entries(
    tmp_path: Path,
) -> None:
    store = GlossaryStore(tmp_path)
    _table(store, "Global", "general", [GlossaryEntry("Kirito", "桐人")])
    task = _task(glossary=TaskGlossary(global_ids=[], use_task=True))
    task_csv = (
        tmp_path
        / "projects"
        / task.project
        / "tasks"
        / task.id
        / "glossary.csv"
    )
    task_csv.parent.mkdir(parents=True)
    task_csv.write_text(
        "source,target,notes,category\r\nSinon,詩乃,,人名\r\n",
        encoding="utf-8",
    )

    assert resolve_effective_glossary(tmp_path, task) == [
        GlossaryEntry("Sinon", "詩乃", "", "人名")
    ]


def test_new_video_task_selects_enabled_video_and_general_tables_in_manifest_order(
    tmp_path: Path,
) -> None:
    store = GlossaryStore(tmp_path)
    general = _table(store, "General", "general", [])
    video = _table(store, "Video", "video", [])
    _table(store, "Document", "document", [])
    _table(store, "Disabled Video", "video", [], enabled=False)

    assert task_glossary_for_new_task(tmp_path, "video") == TaskGlossary(
        global_ids=[general, video],
        use_task=False,
        asr_mode="auto",
    )
