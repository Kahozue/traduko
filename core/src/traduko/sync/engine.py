"""Sync engine: three-way sync of settings against a SyncTarget folder
(design doc section 9).

Scope: config/*.yaml, profiles/*.yaml, prompts/* and glossaries/*.csv sync
both ways; task records push one way to tasks/<machine_id>/ and other
machines' records are pulled into sync/peers/ as a read-only view. Stage
artifacts never sync in v1.

Change detection is a content-hash three-way compare against sync/state.json
(the hash of each file after the last successful sync). The state file is
only an accelerator: files stay the source of truth, and deleting the state
just makes the next run a full compare. When both sides changed, glossaries
get a row-level merge (base copies live in sync/base/) and everything else
falls back to newest-mtime-wins. Deletions do not propagate in v1.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path

from ..config import SyncConfig
from ..models import utc_now_iso
from .merge import merge_glossary
from .targets import LocalFolderTarget, SyncTarget, SyncTargetError, WebDAVTarget

STATE_FILE = "sync/state.json"
CONFLICTS_FILE = "sync/conflicts.json"
MACHINE_FILE = "sync/machine.json"
BASE_DIR = "sync/base"
PEERS_DIR = "sync/peers"

SETTINGS_RULES = (
    ("config", "*.yaml"),
    ("profiles", "*.yaml"),
    ("prompts", "*"),
    ("glossaries", "*.csv"),
    ("glossaries", "manifest.json"),
)


class SyncConfigError(Exception):
    pass


def create_target(config: SyncConfig) -> SyncTarget:
    if config.mode == "folder":
        if not config.folder_path.strip():
            raise SyncConfigError("sync folder path is not configured")
        return LocalFolderTarget(Path(config.folder_path).expanduser())
    if not config.webdav_url.strip():
        raise SyncConfigError("webdav url is not configured")
    return WebDAVTarget(
        config.webdav_url,
        username=config.webdav_username,
        password=config.webdav_password,
    )


def machine_id(root: Path) -> str:
    path = root / MACHINE_FILE
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["machine_id"]
    host = re.sub(r"[^A-Za-z0-9-]+", "-", platform.node()).strip("-") or "machine"
    generated = f"{host}-{secrets.token_hex(2)}"
    _write_local(path, json.dumps({"machine_id": generated}, indent=2).encode())
    return generated


def _write_local(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_settings_rel(rel: str) -> bool:
    parts = rel.split("/")
    if len(parts) != 2:
        return False
    directory, name = parts
    if name.startswith(".") or name.endswith(".tmp"):
        return False
    return any(
        directory == rule_dir and fnmatch(name, pattern)
        for rule_dir, pattern in SETTINGS_RULES
    )


def load_state(root: Path) -> dict:
    path = root / STATE_FILE
    if not path.exists():
        return {"schema_version": 1, "files": {}, "tasks": {}, "peers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(root: Path, state: dict) -> None:
    _write_local(root / STATE_FILE, json.dumps(state, indent=2).encode())


def load_conflicts(root: Path) -> list[dict]:
    path = root / CONFLICTS_FILE
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_conflicts(root: Path, conflicts: list[dict]) -> None:
    _write_local(root / CONFLICTS_FILE, json.dumps(conflicts, indent=2).encode())


def resolve_conflict(root: Path, file: str, source: str, choice: str) -> bool:
    conflicts = load_conflicts(root)
    match = next(
        (c for c in conflicts if c["file"] == file and c["source"] == source), None
    )
    if match is None:
        return False
    if choice == "remote":
        from .merge import parse_rows, render_rows

        path = root / file
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        rows = parse_rows(text)
        rows[source] = match["remote"]
        _write_local(path, render_rows(rows).encode("utf-8"))
    save_conflicts(root, [c for c in conflicts if c is not match])
    return True


def list_peers(root: Path) -> list[dict]:
    peers_dir = root / PEERS_DIR
    if not peers_dir.exists():
        return []
    peers = []
    for machine_dir in sorted(p for p in peers_dir.iterdir() if p.is_dir()):
        tasks = []
        for path in sorted(machine_dir.rglob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            tasks.append(
                {
                    "id": record.get("id", path.stem),
                    "project": record.get("project", ""),
                    "name": record.get("name") or "",
                    "status": record.get("status", ""),
                    "profile": record.get("profile", ""),
                    "created_at": record.get("created_at", ""),
                    "updated_at": record.get("updated_at", ""),
                }
            )
        tasks.sort(key=lambda task: task["updated_at"], reverse=True)
        if tasks:
            peers.append({"machine": machine_dir.name, "tasks": tasks})
    return peers


@dataclass
class SyncReport:
    ok: bool = True
    pushed: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    merged: list[str] = field(default_factory=list)
    conflicts: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SyncEngine:
    def __init__(self, root: Path, target: SyncTarget) -> None:
        self.root = root
        self.target = target
        self.machine_id = machine_id(root)

    def run(self) -> SyncReport:
        report = SyncReport()
        state = load_state(self.root)
        try:
            remote = self.target.list_files()
            self._sync_settings(remote, state, report)
            self._push_tasks(state, report)
            self._pull_peers(remote, state, report)
            self._refresh_remote_mtimes(state, report)
        except (SyncTargetError, OSError) as error:
            report.ok = False
            report.error = str(error)
        report.conflicts = len(load_conflicts(self.root))
        state["last_sync"] = utc_now_iso()
        state["last_result"] = report.to_dict()
        save_state(self.root, state)
        return report

    # -- settings ---------------------------------------------------------

    def _local_settings(self) -> list[str]:
        rels = []
        for directory, pattern in SETTINGS_RULES:
            base = self.root / directory
            if not base.exists():
                continue
            for path in sorted(base.glob(pattern)):
                rel = f"{directory}/{path.name}"
                if path.is_file() and _is_settings_rel(rel):
                    rels.append(rel)
        return rels

    def _sync_settings(
        self, remote: dict[str, float], state: dict, report: SyncReport
    ) -> None:
        remote_settings = {
            rel: mtime for rel, mtime in remote.items() if _is_settings_rel(rel)
        }
        for rel in sorted(set(self._local_settings()) | set(remote_settings)):
            self._sync_one(rel, remote_settings.get(rel), state, report)

    def _sync_one(
        self, rel: str, remote_mtime: float | None, state: dict, report: SyncReport
    ) -> None:
        local_path = self.root / rel
        local_data = local_path.read_bytes() if local_path.exists() else None
        entry = state["files"].get(rel, {})

        if (
            local_data is not None
            and remote_mtime is not None
            and _sha256(local_data) == entry.get("hash")
            and remote_mtime == entry.get("remote_mtime")
        ):
            return  # unchanged on both sides since last sync

        remote_data = self.target.read(rel) if remote_mtime is not None else None
        if remote_data is not None and local_data == remote_data:
            self._record(state, rel, local_data)
            state["files"][rel]["remote_mtime"] = remote_mtime
            return

        if local_data is None and remote_data is not None:
            self._pull(rel, remote_data, state, report)
            return
        if remote_data is None and local_data is not None:
            self._push(rel, local_data, state, report)
            return

        assert local_data is not None and remote_data is not None
        base_hash = entry.get("hash")
        local_changed = _sha256(local_data) != base_hash
        remote_changed = _sha256(remote_data) != base_hash
        if local_changed and not remote_changed:
            self._push(rel, local_data, state, report)
        elif remote_changed and not local_changed:
            self._pull(rel, remote_data, state, report)
        elif rel.startswith("glossaries/") and rel.endswith(".csv"):
            self._merge_glossary(rel, local_data, remote_data, state, report)
        else:
            if local_path.stat().st_mtime >= remote_mtime:
                self._push(rel, local_data, state, report)
            else:
                self._pull(rel, remote_data, state, report)

    def _push(self, rel: str, data: bytes, state: dict, report: SyncReport) -> None:
        self.target.write(rel, data)
        self._record(state, rel, data)
        report.pushed.append(rel)

    def _pull(self, rel: str, data: bytes, state: dict, report: SyncReport) -> None:
        _write_local(self.root / rel, data)
        self._record(state, rel, data)
        report.pulled.append(rel)

    def _merge_glossary(
        self, rel: str, local: bytes, remote: bytes, state: dict, report: SyncReport
    ) -> None:
        base_path = self.root / BASE_DIR / rel
        base_text = base_path.read_text(encoding="utf-8") if base_path.exists() else ""
        merged_text, new_conflicts = merge_glossary(
            base_text, local.decode("utf-8"), remote.decode("utf-8")
        )
        merged = merged_text.encode("utf-8")
        _write_local(self.root / rel, merged)
        self.target.write(rel, merged)
        self._record(state, rel, merged)
        report.merged.append(rel)
        if new_conflicts:
            conflicts = load_conflicts(self.root)
            index = {(c["file"], c["source"]): c for c in conflicts}
            for conflict in new_conflicts:
                index[(rel, conflict["source"])] = {"file": rel, **conflict}
            save_conflicts(self.root, list(index.values()))

    def _record(self, state: dict, rel: str, data: bytes) -> None:
        state["files"][rel] = {"hash": _sha256(data), "remote_mtime": None}
        # Only the per-table CSVs merge row-by-row and need a base copy; the
        # manifest syncs whole-file (mtime wins), so it takes no base.
        if rel.startswith("glossaries/") and rel.endswith(".csv"):
            _write_local(self.root / BASE_DIR / rel, data)

    # -- task records -------------------------------------------------------

    def _push_tasks(self, state: dict, report: SyncReport) -> None:
        for path in sorted((self.root / "projects").glob("*/tasks/*/task.json")):
            project = path.parents[2].name
            task_id = path.parent.name
            rel = f"tasks/{self.machine_id}/{project}/{task_id}.json"
            data = path.read_bytes()
            digest = _sha256(data)
            if state["tasks"].get(rel) == digest:
                continue
            self.target.write(rel, data)
            state["tasks"][rel] = digest
            report.pushed.append(rel)

    def _pull_peers(
        self, remote: dict[str, float], state: dict, report: SyncReport
    ) -> None:
        own_prefix = f"tasks/{self.machine_id}/"
        for rel, mtime in sorted(remote.items()):
            if not rel.startswith("tasks/") or rel.startswith(own_prefix):
                continue
            local_copy = self.root / PEERS_DIR / rel.removeprefix("tasks/")
            if local_copy.exists() and state["peers"].get(rel) == mtime:
                continue
            _write_local(local_copy, self.target.read(rel))
            state["peers"][rel] = mtime
            report.pulled.append(rel)

    # -- state upkeep -------------------------------------------------------

    def _refresh_remote_mtimes(self, state: dict, report: SyncReport) -> None:
        touched = [
            rel
            for rel in report.pushed + report.pulled + report.merged
            if rel in state["files"]
        ]
        stale = [
            rel
            for rel, entry in state["files"].items()
            if entry.get("remote_mtime") is None
        ]
        if not touched and not stale:
            return
        remote = self.target.list_files()
        for rel in set(touched) | set(stale):
            if rel in state["files"] and rel in remote:
                state["files"][rel]["remote_mtime"] = remote[rel]
