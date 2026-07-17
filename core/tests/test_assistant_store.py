from pathlib import Path

import json

import pytest

from traduko.agents import assistant_store
from traduko.workspace import Workspace


def make_ws(tmp_path: Path) -> Workspace:
    return Workspace.open(tmp_path)


def test_first_use_creates_active_session(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    session_id = assistant_store.active_session_id(ws)
    assert session_id.startswith("sess-")
    assert assistant_store.load_messages(ws) == []
    rows = assistant_store.list_sessions(ws)
    assert len(rows) == 1
    assert rows[0]["active"] is True
    assert rows[0]["message_count"] == 0


def test_save_and_load_round_trip_and_title_from_first_user_line(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    messages = [
        {"role": "user", "text": "把每月上限改成 50", "ts": "2026-01-01T00:00:00+00:00"},
        {"role": "assistant", "text": "好的", "ts": "2026-01-01T00:00:01+00:00"},
    ]
    assistant_store.save_messages(ws, messages)
    assert assistant_store.load_messages(ws) == messages
    rows = assistant_store.list_sessions(ws)
    assert rows[0]["title"] == "把每月上限改成 50"
    assert rows[0]["message_count"] == 2


def test_create_session_switches_active_and_isolates_messages(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    assistant_store.save_messages(
        ws, [{"role": "user", "text": "first", "ts": "2026-01-01T00:00:00+00:00"}]
    )
    first = assistant_store.active_session_id(ws)
    second = assistant_store.create_session(ws)
    assert second != first
    assert assistant_store.load_messages(ws) == []
    # Activating the first session brings its messages back.
    assistant_store.activate_session(ws, first)
    assert [m["text"] for m in assistant_store.load_messages(ws)] == ["first"]


def test_archive_and_filter(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    first = assistant_store.active_session_id(ws)
    assistant_store.create_session(ws)
    assistant_store.set_archived(ws, first, True)
    kept = assistant_store.list_sessions(ws, include_archived=False)
    assert first not in [row["id"] for row in kept]
    assert first in [row["id"] for row in assistant_store.list_sessions(ws)]


def test_delete_active_session_opens_a_fresh_one(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    first = assistant_store.active_session_id(ws)
    assistant_store.delete_session(ws, first)
    new_active = assistant_store.active_session_id(ws)
    assert new_active != first
    assert assistant_store.load_messages(ws) == []


def test_truncate_after_drops_tail(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    session_id = assistant_store.active_session_id(ws)
    assistant_store.save_messages(
        ws,
        [
            {"role": "user", "text": "a", "ts": "t"},
            {"role": "assistant", "text": "b", "ts": "t"},
            {"role": "user", "text": "c", "ts": "t"},
            {"role": "assistant", "text": "d", "ts": "t"},
        ],
    )
    kept = assistant_store.truncate_after(ws, session_id, 2)
    assert [m["text"] for m in kept] == ["a", "b"]
    assert [m["text"] for m in assistant_store.load_messages(ws)] == ["a", "b"]


def test_missing_session_raises_key_error(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    with pytest.raises(KeyError):
        assistant_store.get_session(ws, "sess-nope")
    with pytest.raises(KeyError):
        assistant_store.activate_session(ws, "sess-nope")
    with pytest.raises(KeyError):
        assistant_store.delete_session(ws, "sess-nope")


def test_legacy_history_json_is_migrated_into_a_session(tmp_path: Path) -> None:
    ws = make_ws(tmp_path)
    legacy = ws.root / "assistant" / "history.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "text": "legacy hi", "ts": "2026-01-01T00:00:00+00:00"},
                    {"role": "assistant", "text": "legacy reply", "ts": "2026-01-01T00:00:01+00:00"},
                ]
            }
        ),
        encoding="utf-8",
    )
    messages = assistant_store.load_messages(ws)
    assert [m["text"] for m in messages] == ["legacy hi", "legacy reply"]
    # Migration runs once: the legacy file is renamed out of the way.
    assert not legacy.exists()
    assert (ws.root / "assistant" / "history.json.migrated").exists()
