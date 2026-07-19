"""Resolve the glossary entries that apply to one task."""
from __future__ import annotations

from pathlib import Path

from ..models import TaskGlossary, TaskRecord
from .models import GlossaryEntry
from .store import GlossaryStore, parse_import


def task_glossary_for_new_task(root: Path, domain: str) -> TaskGlossary:
    """Select enabled domain and general tables in manifest priority order."""
    store = GlossaryStore(root)
    global_ids = [
        meta.id
        for meta in store.list_tables()
        if meta.enabled and meta.domain in {domain, "general"}
    ]
    return TaskGlossary(global_ids=global_ids, use_task=False, asr_mode="auto")


def resolve_effective_glossary(
    root: Path, task: TaskRecord
) -> list[GlossaryEntry]:
    """Merge selected global tables and the task-local table.

    Global conflicts follow manifest order. The task-local CSV has the final
    say. A record loaded from legacy task.json without a ``glossary`` key
    preserves the pre-v3_5 behavior of using every enabled global table.
    """
    store = GlossaryStore(root)
    if "glossary" not in task.model_fields_set:
        return store.enabled_merged()

    config = task.glossary
    selected = set(config.global_ids)
    merged: dict[str, GlossaryEntry] = {}
    for meta in store.list_tables():
        if meta.id not in selected or not meta.enabled:
            continue
        for entry in store.read_entries(meta.id):
            merged.setdefault(entry.source, entry)

    if config.use_task:
        task_path = (
            root
            / "projects"
            / task.project
            / "tasks"
            / task.id
            / "glossary.csv"
        )
        if task_path.exists():
            for entry in parse_import(task_path.read_text(encoding="utf-8"), "csv"):
                merged[entry.source] = entry

    return list(merged.values())
