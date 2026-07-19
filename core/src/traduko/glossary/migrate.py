"""One-time migration from the pre-v3_5 single-file glossary layout.

Legacy layout: `glossaries/global.csv` plus optional per-project
`glossaries/<project>.csv`, header source,target,notes,scope. New layout: one
CSV per named table plus `glossaries/manifest.json`. Migration is guarded by
manifest.json existence so it runs exactly once; legacy files are renamed
`.migrated` as a backup rather than deleted. The dropped ``scope`` column has
no analogue in the new model, so every legacy row migrates as an uncategorised
entry.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from ..fsutil import atomic_write_text
from .models import GlossaryEntry
from .store import _now, _render_csv, _slugify, _SCHEMA_VERSION


def _read_legacy(path: Path) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    for row in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))):
        source = (row.get("source") or "").strip()
        target = (row.get("target") or "").strip()
        if not source or not target:
            continue
        entries.append(
            GlossaryEntry(
                source=source,
                target=target,
                notes=(row.get("notes") or "").strip(),
                category="",
            )
        )
    return entries


def migrate_legacy_glossaries(root: Path) -> None:
    gdir = root / "glossaries"
    manifest_path = gdir / "manifest.json"
    if manifest_path.exists():
        return

    now = _now()
    order: list[str] = []
    glossaries: dict[str, dict] = {}
    used_ids: set[str] = set()

    def add(table_id: str, name: str, entries: list[GlossaryEntry]) -> None:
        atomic_write_text(gdir / f"{table_id}.csv", _render_csv(entries))
        glossaries[table_id] = {
            "name": name,
            "domain": "general",
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
        order.append(table_id)
        used_ids.add(table_id)

    global_file: Path | None = None
    project_files: list[Path] = []
    if gdir.exists():
        for path in sorted(gdir.glob("*.csv")):
            if path.name == "global.csv":
                global_file = path
            else:
                project_files.append(path)

    # Project tables migrate first so they keep priority over the default,
    # preserving the legacy "project entries win over global" semantics
    # (manifest order is the conflict priority, earlier wins). Rename the
    # legacy file away before writing the new table CSV: when the slug equals
    # the stem the two paths collide, so the write must land on the vacated
    # name.
    for path in project_files:
        entries = _read_legacy(path)
        path.rename(path.with_suffix(".csv.migrated"))
        base = _slugify(path.stem)
        table_id = base
        n = 2
        while table_id in used_ids:
            table_id = f"{base}-{n}"
            n += 1
        add(table_id, f"{path.stem} 名詞表", entries)

    if global_file is not None:
        entries = _read_legacy(global_file)
        global_file.rename(global_file.with_suffix(".csv.migrated"))
        add("default", "預設名詞表", entries)

    atomic_write_text(
        manifest_path,
        json.dumps(
            {"schema_version": _SCHEMA_VERSION, "order": order, "glossaries": glossaries},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
