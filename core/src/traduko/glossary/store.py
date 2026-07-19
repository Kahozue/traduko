"""GlossaryStore: file-backed multi-table glossary model.

Each table is a CSV `glossaries/<id>.csv` with header source,target,notes,category.
`glossaries/manifest.json` records the table order (which is both the UI list
order and the conflict priority, earlier wins) plus per-table metadata. The
store is the single source of truth; HTTP/CLI/agent surfaces are its clients.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ..fsutil import atomic_write_text
from .models import GlossaryEntry, GlossaryTableMeta

_FIELDS = ("source", "target", "notes", "category")
_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "table"


def _empty_manifest() -> dict:
    return {"schema_version": _SCHEMA_VERSION, "order": [], "glossaries": {}}


def _parse_csv(text: str) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    for row in csv.DictReader(io.StringIO(text)):
        source = (row.get("source") or "").strip()
        target = (row.get("target") or "").strip()
        if not source or not target:
            continue
        entries.append(
            GlossaryEntry(
                source=source,
                target=target,
                notes=(row.get("notes") or "").strip(),
                category=(row.get("category") or "").strip(),
            )
        )
    return entries


def _render_csv(entries: list[GlossaryEntry]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=_FIELDS, lineterminator="\r\n")
    writer.writeheader()
    for entry in entries:
        writer.writerow(
            {
                "source": entry.source,
                "target": entry.target,
                "notes": entry.notes,
                "category": entry.category,
            }
        )
    return out.getvalue()


def parse_import(content: str, fmt: str) -> list[GlossaryEntry]:
    """Parse imported glossary content. Rows missing source/target are skipped.

    Raises ValueError on malformed JSON or an unsupported format.
    """
    if fmt == "csv":
        return _parse_csv(content)
    if fmt == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            rows = data.get("entries", [])
        elif isinstance(data, list):
            rows = data
        else:
            rows = []
        entries: list[GlossaryEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or "").strip()
            target = str(row.get("target") or "").strip()
            if not source or not target:
                continue
            entries.append(
                GlossaryEntry(
                    source=source,
                    target=target,
                    notes=str(row.get("notes") or "").strip(),
                    category=str(row.get("category") or "").strip(),
                )
            )
        return entries
    raise ValueError(f"unsupported glossary format: {fmt}")


class GlossaryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._dir = root / "glossaries"
        self._manifest_path = self._dir / "manifest.json"

    # --- manifest -------------------------------------------------------

    def _load_manifest(self) -> dict:
        if not self._manifest_path.exists():
            return _empty_manifest()
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_manifest()
        if not isinstance(data, dict):
            return _empty_manifest()
        data.setdefault("schema_version", _SCHEMA_VERSION)
        data.setdefault("order", [])
        data.setdefault("glossaries", {})
        return data

    def _write_manifest(self, manifest: dict) -> None:
        atomic_write_text(
            self._manifest_path,
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    def _require(self, manifest: dict, table_id: str) -> dict:
        try:
            return manifest["glossaries"][table_id]
        except KeyError:
            raise KeyError(table_id) from None

    def _meta(self, manifest: dict, table_id: str) -> GlossaryTableMeta:
        raw = self._require(manifest, table_id)
        return GlossaryTableMeta(
            id=table_id,
            name=raw["name"],
            domain=raw["domain"],
            enabled=bool(raw["enabled"]),
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )

    def _csv_path(self, table_id: str) -> Path:
        return self._dir / f"{table_id}.csv"

    def _unique_id(self, manifest: dict, base: str) -> str:
        existing = set(manifest["glossaries"])
        if base not in existing:
            return base
        n = 2
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    def _write_entries_file(self, table_id: str, entries: list[GlossaryEntry]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._csv_path(table_id), _render_csv(entries))

    # --- table CRUD -----------------------------------------------------

    def list_tables(self, domain: str | None = None) -> list[GlossaryTableMeta]:
        manifest = self._load_manifest()
        metas: list[GlossaryTableMeta] = []
        for table_id in manifest["order"]:
            if table_id not in manifest["glossaries"]:
                continue
            meta = self._meta(manifest, table_id)
            if domain is not None and meta.domain != domain:
                continue
            metas.append(meta)
        return metas

    def get_table(self, table_id: str) -> GlossaryTableMeta:
        return self._meta(self._load_manifest(), table_id)

    def create_table(self, name: str, domain: str) -> GlossaryTableMeta:
        manifest = self._load_manifest()
        table_id = self._unique_id(manifest, _slugify(name))
        now = _now()
        manifest["glossaries"][table_id] = {
            "name": name,
            "domain": domain,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
        manifest["order"].append(table_id)
        self._write_entries_file(table_id, [])
        self._write_manifest(manifest)
        return self._meta(manifest, table_id)

    def rename_table(self, table_id: str, name: str) -> GlossaryTableMeta:
        manifest = self._load_manifest()
        raw = self._require(manifest, table_id)
        raw["name"] = name
        raw["updated_at"] = _now()
        self._write_manifest(manifest)
        return self._meta(manifest, table_id)

    def set_enabled(self, table_id: str, enabled: bool) -> GlossaryTableMeta:
        manifest = self._load_manifest()
        raw = self._require(manifest, table_id)
        raw["enabled"] = bool(enabled)
        raw["updated_at"] = _now()
        self._write_manifest(manifest)
        return self._meta(manifest, table_id)

    def delete_table(self, table_id: str) -> None:
        manifest = self._load_manifest()
        self._require(manifest, table_id)
        del manifest["glossaries"][table_id]
        manifest["order"] = [i for i in manifest["order"] if i != table_id]
        self._csv_path(table_id).unlink(missing_ok=True)
        self._write_manifest(manifest)

    # --- entries --------------------------------------------------------

    def read_entries(self, table_id: str) -> list[GlossaryEntry]:
        self.get_table(table_id)  # raises KeyError if unknown
        path = self._csv_path(table_id)
        if not path.exists():
            return []
        return _parse_csv(path.read_text(encoding="utf-8"))

    def write_entries(
        self, table_id: str, entries: list[GlossaryEntry], *, now: str | None = None
    ) -> None:
        manifest = self._load_manifest()
        raw = self._require(manifest, table_id)
        self._write_entries_file(table_id, entries)
        raw["updated_at"] = now or _now()
        self._write_manifest(manifest)

    # --- import / export / merge ---------------------------------------

    def import_table(
        self, name: str, domain: str, content: str, fmt: str
    ) -> GlossaryTableMeta:
        entries = parse_import(content, fmt)
        meta = self.create_table(name, domain)
        self.write_entries(meta.id, entries)
        return self.get_table(meta.id)

    def export_table(self, table_id: str, fmt: str) -> str:
        meta = self.get_table(table_id)
        entries = self.read_entries(table_id)
        if fmt == "json":
            return json.dumps(
                {
                    "name": meta.name,
                    "domain": meta.domain,
                    "entries": [
                        {
                            "source": e.source,
                            "target": e.target,
                            "notes": e.notes,
                            "category": e.category,
                        }
                        for e in entries
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        return _render_csv(entries)

    def enabled_merged(self, domain: str | None = None) -> list[GlossaryEntry]:
        merged: dict[str, GlossaryEntry] = {}
        for meta in self.list_tables(domain):
            if not meta.enabled:
                continue
            for entry in self.read_entries(meta.id):
                merged.setdefault(entry.source, entry)
        return list(merged.values())
