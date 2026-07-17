"""Assistant conversation store: sessions as human-readable JSON files.

Each session is one file at ``assistant/sessions/<id>.json`` holding its
metadata and full message list; the active session is named in
``assistant/active.json``. This mirrors the project's file-first model (the
same as tasks and proposals): the store is queryable like a database but
every conversation is a plain file the user can read, back up, or delete by
hand.

A legacy single ``assistant/history.json`` (the v2-06 shape) is migrated
into one session the first time the store is opened, so upgrading never
loses the existing conversation.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from ..fsutil import atomic_write_text
from ..workspace import Workspace

SESSIONS_DIR = "assistant/sessions"
ACTIVE_FILE = "assistant/active.json"
LEGACY_HISTORY = "assistant/history.json"
# Derived session titles are cut here so the history list stays scannable;
# the full first message still lives in the session file.
TITLE_MAX = 40


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sessions_dir(ws: Workspace) -> Path:
    return ws.root / SESSIONS_DIR


def _session_path(ws: Workspace, session_id: str) -> Path:
    return _sessions_dir(ws) / f"{session_id}.json"


def _new_id(ws: Workspace) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    while True:
        session_id = f"sess-{stamp}-{secrets.token_hex(2)}"
        if not _session_path(ws, session_id).exists():
            return session_id


def _valid_messages(messages: object) -> list[dict]:
    if not isinstance(messages, list):
        return []
    return [message for message in messages if isinstance(message, dict)]


def _read_session(ws: Workspace, session_id: str) -> dict | None:
    path = _session_path(ws, session_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", session_id)
    data["messages"] = _valid_messages(data.get("messages"))
    data.setdefault("archived", False)
    data.setdefault("created_at", _now())
    data.setdefault("updated_at", data["created_at"])
    data.setdefault("title", _derive_title(data["messages"]))
    return data


def _write_session(ws: Workspace, session: dict) -> None:
    atomic_write_text(
        _session_path(ws, session["id"]),
        json.dumps(session, ensure_ascii=False, indent=2),
    )


def _derive_title(messages: list[dict]) -> str:
    for message in messages:
        if message.get("role") == "user":
            text = " ".join(str(message.get("text", "")).split())
            if text:
                return text[:TITLE_MAX]
    return "新對話"


def _read_active_id(ws: Workspace) -> str | None:
    path = ws.root / ACTIVE_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    active = data.get("active") if isinstance(data, dict) else None
    return active if isinstance(active, str) else None


def _write_active_id(ws: Workspace, session_id: str) -> None:
    atomic_write_text(
        ws.root / ACTIVE_FILE, json.dumps({"active": session_id}, ensure_ascii=False)
    )


def _migrate_legacy(ws: Workspace) -> None:
    """One-time move of assistant/history.json into a single session."""
    legacy = ws.root / LEGACY_HISTORY
    if not legacy.exists() or _sessions_dir(ws).exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    messages = _valid_messages(data.get("messages") if isinstance(data, dict) else None)
    session_id = _new_id(ws)
    session = {
        "id": session_id,
        "title": _derive_title(messages),
        "archived": False,
        "created_at": _now(),
        "updated_at": _now(),
        "messages": messages,
    }
    _write_session(ws, session)
    _write_active_id(ws, session_id)
    # Keep the legacy file as a backup but rename so migration runs once.
    legacy.rename(legacy.with_suffix(".json.migrated"))


def _ensure_active(ws: Workspace) -> str:
    """Return the active session id, creating a fresh session if needed."""
    _migrate_legacy(ws)
    active = _read_active_id(ws)
    if active is not None and _session_path(ws, active).exists():
        return active
    # No active session (fresh install, or the active one was deleted): open
    # a new empty one so the panel always has somewhere to write.
    session_id = _new_id(ws)
    _write_session(
        ws,
        {
            "id": session_id,
            "title": "新對話",
            "archived": False,
            "created_at": _now(),
            "updated_at": _now(),
            "messages": [],
        },
    )
    _write_active_id(ws, session_id)
    return session_id


def active_session_id(ws: Workspace) -> str:
    return _ensure_active(ws)


def load_messages(ws: Workspace) -> list[dict]:
    """Messages of the active session (the v2-06 load_history shape)."""
    session = _read_session(ws, _ensure_active(ws))
    return session["messages"] if session else []


def save_messages(ws: Workspace, messages: list[dict]) -> None:
    """Replace the active session's messages, refreshing title and mtime."""
    session_id = _ensure_active(ws)
    session = _read_session(ws, session_id) or {
        "id": session_id,
        "archived": False,
        "created_at": _now(),
    }
    session["messages"] = messages
    session["updated_at"] = _now()
    # Keep the derived title following the first user line until the user
    # never renamed it (renaming is not yet exposed; derive always).
    session["title"] = _derive_title(messages)
    _write_session(ws, session)


def list_sessions(ws: Workspace, *, include_archived: bool = True) -> list[dict]:
    """Session metadata (no message bodies), newest first."""
    _ensure_active(ws)
    active = _read_active_id(ws)
    directory = _sessions_dir(ws)
    rows: list[dict] = []
    if directory.is_dir():
        for path in directory.glob("sess-*.json"):
            session = _read_session(ws, path.stem)
            if session is None:
                continue
            if session["archived"] and not include_archived:
                continue
            rows.append(
                {
                    "id": session["id"],
                    "title": session["title"],
                    "archived": session["archived"],
                    "created_at": session["created_at"],
                    "updated_at": session["updated_at"],
                    "message_count": len(session["messages"]),
                    "active": session["id"] == active,
                }
            )
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    return rows


def get_session(ws: Workspace, session_id: str) -> dict:
    session = _read_session(ws, session_id)
    if session is None:
        raise KeyError(session_id)
    return session


def create_session(ws: Workspace) -> str:
    """Open a new empty session and make it active."""
    _ensure_active(ws)
    session_id = _new_id(ws)
    _write_session(
        ws,
        {
            "id": session_id,
            "title": "新對話",
            "archived": False,
            "created_at": _now(),
            "updated_at": _now(),
            "messages": [],
        },
    )
    _write_active_id(ws, session_id)
    return session_id


def activate_session(ws: Workspace, session_id: str) -> None:
    if not _session_path(ws, session_id).exists():
        raise KeyError(session_id)
    _write_active_id(ws, session_id)


def set_archived(ws: Workspace, session_id: str, archived: bool) -> None:
    session = _read_session(ws, session_id)
    if session is None:
        raise KeyError(session_id)
    session["archived"] = archived
    session["updated_at"] = _now()
    _write_session(ws, session)


def delete_session(ws: Workspace, session_id: str) -> None:
    path = _session_path(ws, session_id)
    if not path.exists():
        raise KeyError(session_id)
    path.unlink()
    # Deleting the active session leaves no pointer; the next _ensure_active
    # opens a fresh one.
    if _read_active_id(ws) == session_id:
        (ws.root / ACTIVE_FILE).unlink(missing_ok=True)


def truncate_after(ws: Workspace, session_id: str, index: int) -> list[dict]:
    """Drop every message from ``index`` onward in a session and return the
    kept prefix. Used by edit-and-resend: the edited user message and its
    stale reply are removed before the new turn runs."""
    session = _read_session(ws, session_id)
    if session is None:
        raise KeyError(session_id)
    kept = session["messages"][: max(0, index)]
    session["messages"] = kept
    session["updated_at"] = _now()
    session["title"] = _derive_title(kept)
    _write_session(ws, session)
    return kept
