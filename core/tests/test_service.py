import asyncio
import json
import logging
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from traduko import proposals
from traduko.config import load_config
from traduko.events import Event
from traduko.notify import _CHANNELS, DEFAULT_EVENTS, register_channel, resolve_events
from traduko.service.app import create_app
from traduko.service.broadcast import WsBroadcaster
from traduko.service.systemlog import setup_system_log
from traduko.stages import registry
from traduko.stages.base import StageContext, StageResult


@contextmanager
def service(tmp_path: Path):
    app = create_app(tmp_path)
    token = (tmp_path / "config" / "api-token").read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        yield client, headers, token


@contextmanager
def memo_channel(name: str = "memo"):
    """Register an in-memory channel type; yields the captured events."""
    captured: list[Event] = []

    @register_channel(name)
    class MemoChannel:
        def __init__(self, events: list[str] | None = None, **_ignored) -> None:
            self.events = resolve_events(events, DEFAULT_EVENTS)

        def send(self, event: Event) -> None:
            captured.append(event)

    try:
        yield captured
    finally:
        _CHANNELS.pop(name, None)


def test_health_needs_no_token(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_requests_without_token_are_rejected(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert client.get("/budget").status_code == 401
        bad = {"Authorization": "Bearer wrong"}
        assert client.get("/budget", headers=bad).status_code == 401


def test_budget_endpoint_reports_usage_and_limits(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/budget", headers=headers)
        assert response.status_code == 200
        assert response.json() == {
            "month_usd": 0.0,
            "task_usd_limit": None,
            "monthly_usd_limit": None,
            "tasks": [],
        }


def test_cors_allows_browser_based_clients(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/health", headers={"Origin": "tauri://localhost"})
        assert response.headers["access-control-allow-origin"] == "*"


def test_token_is_stable_across_restarts(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        first = token
    with service(tmp_path) as (client, headers, token):
        assert token == first


SRT = "1\n00:00:00,000 --> 00:00:01,000\nhi\n"


def make_input(tmp_path: Path) -> Path:
    path = tmp_path / "in.srt"
    path.write_text(SRT, encoding="utf-8")
    return path


def create_task(client, headers, tmp_path: Path, profile: str = "subtitle-translate") -> str:
    response = client.post(
        "/tasks",
        json={"input_path": str(make_input(tmp_path)), "profile": profile},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@registry.register
class ServiceGateStage:
    type = "svc-gate"
    gate = threading.Event()
    started = threading.Event()

    def run(self, ctx: StageContext) -> StageResult:
        type(self).started.set()
        assert type(self).gate.wait(timeout=10)
        return StageResult()


def create_profile(tmp_path: Path, name: str, stages: list[str]) -> None:
    (tmp_path / "profiles").mkdir(exist_ok=True)
    stage_lines = "".join(f"  - type: {s}\n" for s in stages)
    (tmp_path / "profiles" / f"{name}.yaml").write_text(
        f"schema_version: 1\nname: {name}\nstages:\n{stage_lines}", encoding="utf-8"
    )


def test_create_show_list_roundtrip(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        shown = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        assert shown["status"] == "pending"
        assert shown["profile"] == "subtitle-translate"
        rows = client.get("/tasks", headers=headers).json()
        assert [row["id"] for row in rows] == [task_id]


def test_show_unknown_task_is_404(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert client.get("/tasks/default/nope", headers=headers).status_code == 404


def test_create_with_unknown_profile_is_404(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/tasks",
            json={"input_path": str(make_input(tmp_path)), "profile": "nope"},
            headers=headers,
        )
        assert response.status_code == 404


def test_create_with_missing_input_is_400(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/tasks",
            json={
                "input_path": str(tmp_path / "missing.srt"),
                "profile": "subtitle-translate",
            },
            headers=headers,
        )
        assert response.status_code == 400


def test_preflight_endpoint_reports_checks(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        report = client.get(
            f"/tasks/default/{task_id}/preflight", headers=headers
        ).json()
        assert report["ok"] is True
        names = [check["name"] for check in report["checks"]]
        assert "input" in names and "budget" in names

        (tmp_path / "in.srt").unlink()
        report = client.get(
            f"/tasks/default/{task_id}/preflight", headers=headers
        ).json()
        assert report["ok"] is False


def test_profiles_lists_seeded_profiles(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        names = client.get("/profiles", headers=headers).json()
        assert "subtitle-translate" in names and "av-default" in names


PASSTHROUGH = "schema_version: 1\nname: passthrough\nstages:\n  - type: noop\n"


def write_passthrough(tmp_path: Path) -> None:
    (tmp_path / "profiles").mkdir(exist_ok=True)
    (tmp_path / "profiles" / "passthrough.yaml").write_text(
        PASSTHROUGH, encoding="utf-8"
    )


def wait_completed(
    client, headers, project: str, task_id: str, timeout: float = 5.0
) -> dict:
    deadline = time.monotonic() + timeout
    shown = client.get(f"/tasks/{project}/{task_id}", headers=headers).json()
    while time.monotonic() < deadline:
        shown = client.get(f"/tasks/{project}/{task_id}", headers=headers).json()
        if shown["status"] in {"completed", "failed", "canceled"}:
            return shown
        time.sleep(0.01)
    raise AssertionError(f"timed out, last status {shown['status']}")


def test_run_executes_task(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        response = client.post(f"/tasks/default/{task_id}/run", headers=headers)
        assert response.status_code == 202, response.text
        assert response.json() == {"queued": True}
        shown = wait_completed(client, headers, "default", task_id)
        assert shown["status"] == "completed"


def test_run_gates_on_preflight(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        (tmp_path / "in.srt").unlink()
        denied = client.post(f"/tasks/default/{task_id}/run", headers=headers)
        assert denied.status_code == 409
        assert denied.json()["detail"]["checks"][0]["name"] == "input"
        shown = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        assert shown["status"] == "pending"

        forced = client.post(
            f"/tasks/default/{task_id}/run",
            json={"skip_preflight": True},
            headers=headers,
        )
        assert forced.status_code == 202
        assert wait_completed(client, headers, "default", task_id)["status"] == "completed"


def test_run_rejects_completed_task(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        client.post(f"/tasks/default/{task_id}/run", headers=headers)
        wait_completed(client, headers, "default", task_id)
        again = client.post(f"/tasks/default/{task_id}/run", headers=headers)
        assert again.status_code == 409


def test_cancel_pending_task(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        response = client.post(f"/tasks/default/{task_id}/cancel", headers=headers)
        assert response.status_code == 202
        assert response.json() == {"canceled": True}
        shown = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        assert shown["status"] == "canceled"


def test_cancel_completed_task_is_409(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        client.post(f"/tasks/default/{task_id}/run", headers=headers)
        wait_completed(client, headers, "default", task_id)
        response = client.post(f"/tasks/default/{task_id}/cancel", headers=headers)
        assert response.status_code == 409


def test_broadcaster_delivers_across_threads() -> None:
    async def scenario() -> dict:
        broadcaster = WsBroadcaster()
        client_id, queue = broadcaster.register()
        event = Event(type="task_completed", task_id="t1", project="p", data={})
        thread = threading.Thread(target=broadcaster.handle, args=(event,))
        thread.start()
        thread.join()
        payload = await asyncio.wait_for(queue.get(), timeout=2)
        broadcaster.unregister(client_id)
        return payload

    payload = asyncio.run(scenario())
    assert payload["type"] == "task_completed"
    assert payload["task_id"] == "t1" and payload["project"] == "p"


def test_ws_rejects_bad_token(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/events?token=wrong"):
                pass


def test_ws_streams_bus_events(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        with client.websocket_connect(f"/ws/events?token={token}") as stream:
            client.app.state.workspace.bus.publish(
                Event(
                    type="task_started",
                    task_id="t9",
                    project="p",
                    data={"stage_total": 1},
                )
            )
            payload = stream.receive_json()
    assert payload["type"] == "task_started"
    assert payload["task_id"] == "t9"
    assert payload["data"] == {"stage_total": 1}


def test_system_log_captures_package_logs(tmp_path: Path) -> None:
    path = setup_system_log(tmp_path)
    logging.getLogger("traduko.smoke").info("hello system log")
    assert path == tmp_path / "logs" / "core.log"
    assert "hello system log" in path.read_text(encoding="utf-8")


def test_run_via_api_writes_task_event_log(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        client.post(f"/tasks/default/{task_id}/run", headers=headers)
        wait_completed(client, headers, "default", task_id)
    log_path = (
        tmp_path / "projects" / "default" / "tasks" / task_id
        / "logs" / "events.jsonl"
    )
    types = [
        json.loads(line)["type"]
        for line in log_path.read_text(encoding="utf-8").strip().splitlines()
    ]
    assert types[0] == "task_started"
    assert types[-1] == "task_completed"


def test_get_config_returns_defaults(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/config", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["default_project"] == "default"
        assert body["budget"]["task_usd_limit"] is None
        assert body["notifications"]["channels"] == []


def test_put_config_persists_and_takes_effect(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        config = client.get("/config", headers=headers).json()
        config["default_project"] = "movies"
        config["budget"]["monthly_usd_limit"] = 25.0
        config["llm_providers"]["deepseek"] = {
            "type": "openai_compat",
            "base_url": "https://api.deepseek.com/v1",
            "api_key_env": "DEEPSEEK_API_KEY",
        }
        response = client.put("/config", headers=headers, json=config)
        assert response.status_code == 200
        assert response.json()["default_project"] == "movies"

        on_disk = load_config(tmp_path)
        assert on_disk.default_project == "movies"
        assert on_disk.budget.monthly_usd_limit == 25.0
        assert on_disk.llm_providers["deepseek"]["api_key_env"] == "DEEPSEEK_API_KEY"

        budget = client.get("/budget", headers=headers).json()
        assert budget["monthly_usd_limit"] == 25.0


def test_put_config_rejects_invalid_document(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        original = client.get("/config", headers=headers).json()

        bad_types = dict(original)
        bad_types["budget"] = {"task_usd_limit": "lots"}
        assert client.put("/config", headers=headers, json=bad_types).status_code == 422

        bad_channel = dict(original)
        bad_channel["notifications"] = {"channels": [{"type": "carrier_pigeon"}]}
        assert (
            client.put("/config", headers=headers, json=bad_channel).status_code == 422
        )

        empty_project = dict(original)
        empty_project["default_project"] = "  "
        assert (
            client.put("/config", headers=headers, json=empty_project).status_code
            == 422
        )

        on_disk = load_config(tmp_path)
        assert on_disk.default_project == "default"


def test_put_config_rebuilds_notification_channels(tmp_path: Path) -> None:
    with memo_channel() as captured:
        with service(tmp_path) as (client, headers, token):
            config = client.get("/config", headers=headers).json()
            config["notifications"] = {"channels": [{"type": "memo"}]}
            assert client.put("/config", headers=headers, json=config).status_code == 200

            bus = client.app.state.workspace.bus
            bus.publish(
                Event(type="task_completed", task_id="t1", project="p", data={})
            )
            assert [e.type for e in captured] == ["task_completed"]

            config["notifications"] = {"channels": []}
            assert client.put("/config", headers=headers, json=config).status_code == 200
            bus.publish(Event(type="task_failed", task_id="t1", project="p", data={}))
            assert [e.type for e in captured] == ["task_completed"]


def test_notification_test_endpoint_reports_success(tmp_path: Path) -> None:
    with memo_channel() as captured:
        with service(tmp_path) as (client, headers, token):
            response = client.post(
                "/config/notifications/test",
                headers=headers,
                json={"channel": {"type": "memo"}},
            )
            assert response.status_code == 200
            assert response.json() == {"ok": True}
            assert captured[0].type == "task_completed"


def test_notification_test_endpoint_reports_delivery_failure(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/config/notifications/test",
            headers=headers,
            json={
                "channel": {
                    "type": "webhook",
                    "url": "http://127.0.0.1:9/hook",
                    "timeout": 0.2,
                }
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["error"]


def test_notification_test_endpoint_rejects_bad_channel(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        unknown = client.post(
            "/config/notifications/test",
            headers=headers,
            json={"channel": {"type": "carrier_pigeon"}},
        )
        assert unknown.status_code == 422

        missing_field = client.post(
            "/config/notifications/test",
            headers=headers,
            json={"channel": {"type": "webhook"}},
        )
        assert missing_field.status_code == 422


def test_pause_endpoint_validates_task_state(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        missing = client.post("/tasks/default/none/pause", headers=headers)
        assert missing.status_code == 404
        task_id = create_task(client, headers, tmp_path)
        idle = client.post(f"/tasks/default/{task_id}/pause", headers=headers)
        assert idle.status_code == 409


def test_pause_endpoint_pauses_running_task(tmp_path: Path) -> None:
    ServiceGateStage.gate = threading.Event()
    ServiceGateStage.started = threading.Event()
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "gated", ["svc-gate", "noop"])
        task_id = create_task(client, headers, tmp_path, profile="gated")
        url = f"/tasks/default/{task_id}"
        assert client.post(f"{url}/run", headers=headers).status_code == 202
        assert ServiceGateStage.started.wait(timeout=5)
        response = client.post(f"{url}/pause", headers=headers)
        assert response.status_code == 202
        assert response.json() == {"pausing": True}
        ServiceGateStage.gate.set()
        status = ""
        for _ in range(250):
            status = client.get(url, headers=headers).json()["status"]
            if status == "paused":
                break
            time.sleep(0.02)
        assert status == "paused"


def test_lifespan_starts_bot_when_enabled(tmp_path: Path, monkeypatch) -> None:
    import traduko.bot.runner as bot_runner

    started: list[str] = []

    async def fake_run_bot(app, config) -> None:
        started.append(config.bot_token)
        await asyncio.Event().wait()

    monkeypatch.setattr(bot_runner, "run_bot", fake_run_bot)
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "core.yaml").write_text(
        "discord_bot:\n  enabled: true\n  bot_token: t0k\n", encoding="utf-8"
    )
    with service(tmp_path) as (client, headers, token):
        assert client.get("/health").status_code == 200
    assert started == ["t0k"]


def test_lifespan_skips_bot_without_token(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "core.yaml").write_text(
        "discord_bot:\n  enabled: true\n", encoding="utf-8"
    )
    with service(tmp_path) as (client, headers, token):
        assert client.get("/health").status_code == 200


def _enable_sync(client, headers, folder: Path) -> None:
    config = client.get("/config", headers=headers).json()
    config["sync"] = {**config["sync"], "enabled": True, "mode": "folder",
                      "folder_path": str(folder)}
    assert client.put("/config", headers=headers, json=config).status_code == 200


def test_sync_status_and_run_when_disabled(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        status = client.get("/sync/status", headers=headers).json()
        assert status["enabled"] is False
        assert status["syncing"] is False
        assert status["last_sync"] is None
        assert status["conflicts"] == []
        assert status["peers"] == []
        assert client.post("/sync/run", headers=headers).status_code == 400


def test_sync_run_pushes_and_status_reports(tmp_path: Path) -> None:
    remote = tmp_path / "cloud"
    with service(tmp_path / "data") as (client, headers, token):
        _enable_sync(client, headers, remote)
        response = client.post("/sync/run", headers=headers)
        assert response.status_code == 200
        report = response.json()
        assert report["ok"] is True
        assert "config/core.yaml" in report["pushed"]
        status = client.get("/sync/status", headers=headers).json()
        assert status["enabled"] is True
        assert status["last_sync"]
        assert status["last_result"]["ok"] is True


def test_sync_pull_reloads_core_config_in_place(tmp_path: Path) -> None:
    import os as _os
    import yaml as _yaml

    remote = tmp_path / "cloud"
    with service(tmp_path / "data") as (client, headers, token):
        _enable_sync(client, headers, remote)
        assert client.post("/sync/run", headers=headers).status_code == 200
        config = client.get("/config", headers=headers).json()
        config["default_project"] = "from-remote"
        remote_yaml = remote / "config" / "core.yaml"
        remote_yaml.write_text(_yaml.safe_dump(config), encoding="utf-8")
        future = time.time() + 3600
        _os.utime(remote_yaml, (future, future))
        report = client.post("/sync/run", headers=headers).json()
        assert "config/core.yaml" in report["pulled"]
        assert (
            client.get("/config", headers=headers).json()["default_project"]
            == "from-remote"
        )


def test_sync_resolve_unknown_conflict_is_404(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/sync/resolve",
            headers=headers,
            json={"file": "glossaries/global.csv", "source": "x", "choice": "remote"},
        )
        assert response.status_code == 404


def test_sync_scheduler_fires_and_stops() -> None:
    from traduko.service.syncsched import SyncScheduler

    calls: list[float] = []
    done = threading.Event()

    def tick() -> None:
        calls.append(time.time())
        if len(calls) >= 2:
            done.set()

    scheduler = SyncScheduler(0.01, tick)
    scheduler.start()
    assert done.wait(timeout=5)
    scheduler.stop()
    count = len(calls)
    time.sleep(0.05)
    assert len(calls) == count


def test_task_events_endpoint_reads_persisted_log(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)

        empty = client.get(f"/tasks/default/{task_id}/events", headers=headers)
        assert empty.status_code == 200
        assert empty.json() == []

        log_dir = tmp_path / "projects" / "default" / "tasks" / task_id / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        entries = [
            {"ts": f"2026-07-17T00:00:0{i}+00:00", "type": "stage_started", "data": {"n": i}}
            for i in range(3)
        ]
        with (log_dir / "events.jsonl").open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        full = client.get(f"/tasks/default/{task_id}/events", headers=headers)
        assert full.status_code == 200
        assert full.json() == entries

        tail = client.get(f"/tasks/default/{task_id}/events?limit=2", headers=headers)
        assert tail.json() == entries[1:]

        missing = client.get("/tasks/default/nope/events", headers=headers)
        assert missing.status_code == 404


def test_budget_endpoint_breaks_down_per_task_spend(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "subtitle-translate",
                "name": "第七話",
            },
            headers=headers,
        )
        assert response.status_code == 201
        task_id = response.json()["id"]

        from datetime import datetime, timezone

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        ledger = tmp_path / "budget" / f"ledger-{month}.jsonl"
        ledger.parent.mkdir(exist_ok=True)
        rows = [
            {"ts": "t", "project": "default", "task_id": task_id, "cost_usd": 0.5},
            {"ts": "t", "project": "default", "task_id": task_id, "cost_usd": 0.25},
            {"ts": "t", "project": "old", "task_id": "gone", "cost_usd": 2.0},
        ]
        with ledger.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

        data = client.get("/budget", headers=headers).json()
        assert data["month_usd"] == pytest.approx(2.75)
        assert data["tasks"] == [
            {"task_id": "gone", "project": "old", "name": None, "usd": 2.0},
            {"task_id": task_id, "project": "default", "name": "第七話", "usd": 0.75},
        ]


def test_delete_task_removes_files_and_index(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        response = client.delete(f"/tasks/default/{task_id}", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"deleted": True}
        assert client.get(f"/tasks/default/{task_id}", headers=headers).status_code == 404
        assert client.get("/tasks", headers=headers).json() == []
        assert not (tmp_path / "projects" / "default" / "tasks" / task_id).exists()


def test_delete_missing_task_is_404(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert client.delete("/tasks/default/none", headers=headers).status_code == 404


def test_delete_and_move_reject_active_task(tmp_path: Path) -> None:
    ServiceGateStage.gate = threading.Event()
    ServiceGateStage.started = threading.Event()
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "gated", ["svc-gate", "noop"])
        task_id = create_task(client, headers, tmp_path, profile="gated")
        url = f"/tasks/default/{task_id}"
        assert client.post(f"{url}/run", headers=headers).status_code == 202
        assert ServiceGateStage.started.wait(timeout=5)
        assert client.delete(url, headers=headers).status_code == 409
        moved = client.patch(url, json={"project": "other"}, headers=headers)
        assert moved.status_code == 409
        ServiceGateStage.gate.set()
        wait_completed(client, headers, "default", task_id)
        assert client.delete(url, headers=headers).status_code == 200


def test_move_task_to_new_project(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        response = client.patch(
            f"/tasks/default/{task_id}",
            json={"project": "anime", "name": "第一話"},
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["project"] == "anime"
        assert body["name"] == "第一話"
        assert client.get(f"/tasks/default/{task_id}", headers=headers).status_code == 404
        shown = client.get(f"/tasks/anime/{task_id}", headers=headers).json()
        assert shown["project"] == "anime"
        rows = client.get("/tasks", headers=headers).json()
        assert [(row["project"], row["name"]) for row in rows] == [("anime", "第一話")]
        assert (tmp_path / "projects" / "anime" / "tasks" / task_id / "task.json").exists()
        assert not (tmp_path / "projects" / "default" / "tasks" / task_id).exists()


def test_patch_task_requires_a_field(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        assert (
            client.patch(f"/tasks/default/{task_id}", json={}, headers=headers).status_code
            == 422
        )
        assert (
            client.patch(
                f"/tasks/default/{task_id}", json={"project": "  "}, headers=headers
            ).status_code
            == 422
        )


def test_asr_status_download_and_test_flow(tmp_path: Path, monkeypatch) -> None:
    from traduko import asrsetup
    from traduko.asrsetup import AsrManager

    cache = tmp_path / "hf-cache"

    def fake_download(model_size: str) -> None:
        snap = asrsetup.model_dir(model_size, cache) / "snapshots" / "abc"
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "model.bin").write_bytes(b"x" * (2 * 1024 * 1024))

    monkeypatch.setattr(asrsetup, "package_available", lambda: True)
    with service(tmp_path) as (client, headers, token):
        client.app.state.asr = AsrManager(
            download=fake_download,
            probe=lambda model: {"ok": True, "load_seconds": 0.1},
            cache_dir=cache,
        )
        status = client.get("/asr/status?model=small", headers=headers).json()
        assert status["package"] is True
        assert status["cached"] is False

        blocked = client.post("/asr/test", json={"model": "small"}, headers=headers)
        assert blocked.status_code == 409

        started = client.post("/asr/download", json={"model": "small"}, headers=headers)
        assert started.status_code == 202

        deadline = time.monotonic() + 5
        status = client.get("/asr/status?model=small", headers=headers).json()
        while time.monotonic() < deadline and status["state"] != "done":
            status = client.get("/asr/status?model=small", headers=headers).json()
        assert status["cached"] is True
        assert status["downloaded_mb"] > 0

        result = client.post("/asr/test", json={"model": "small"}, headers=headers).json()
        assert result == {"ok": True, "load_seconds": 0.1}


def test_asr_download_without_package_is_409(tmp_path: Path, monkeypatch) -> None:
    from traduko import asrsetup

    monkeypatch.setattr(asrsetup, "package_available", lambda: False)
    with service(tmp_path) as (client, headers, token):
        response = client.post("/asr/download", json={"model": "small"}, headers=headers)
        assert response.status_code == 409


def test_mcp_status_empty_without_servers(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, _token):
        resp = client.get("/mcp/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == []


def test_mcp_reload_picks_up_saved_config(tmp_path: Path, monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from test_mcphub import ECHO_TOOL, FakeSession, text_result
    from traduko import mcphub
    from traduko.config import CoreConfig, save_config

    session = FakeSession([ECHO_TOOL], {"echo": text_result("echo:hi")})

    @asynccontextmanager
    async def fake_connector(config):
        yield session

    monkeypatch.setattr(mcphub, "default_connector", fake_connector)
    with service(tmp_path) as (client, headers, _token):
        assert client.get("/mcp/status", headers=headers).json() == []
        config = load_config(tmp_path)
        payload = config.model_dump()
        payload["mcp_servers"] = {
            "demo": {"transport": "stdio", "command": "demo-cmd", "enabled": True}
        }
        save_config(tmp_path, CoreConfig.model_validate(payload))

        resp = client.post("/mcp/reload", headers=headers)
        assert resp.status_code == 200
        deadline = time.monotonic() + 5
        while True:
            rows = client.get("/mcp/status", headers=headers).json()
            if rows and rows[0]["state"] == "connected":
                break
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert rows[0]["name"] == "demo"
        assert rows[0]["tools"] == [
            {"name": "echo", "description": "Echo the text back."}
        ]
        assert mcphub.active_tools()[0].name == "demo.echo"


VALID_SKILL = """---
name: honorific-style
description: Keep honorifics consistent across the translation.
---

Always keep the source honorifics in the target text.
"""


def test_skills_and_proposals_require_token(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert client.get("/skills").status_code == 401
        assert client.get("/proposals").status_code == 401


def test_skills_list_empty_without_skills(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/skills", headers=headers)
        assert response.status_code == 200
        assert response.json() == []


def test_skills_crud_full_flow(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        created = client.post(
            "/skills", json={"name": "honorific-style"}, headers=headers
        )
        assert created.status_code == 201, created.text

        rows = client.get("/skills", headers=headers).json()
        assert [row["name"] for row in rows] == ["honorific-style"]
        assert rows[0]["enabled"] is False
        assert rows[0]["confirmed"] is False
        assert rows[0]["valid"] is True

        shown = client.get("/skills/honorific-style", headers=headers)
        assert shown.status_code == 200
        assert shown.json()["name"] == "honorific-style"
        assert "name: honorific-style" in shown.json()["content"]

        saved = client.put(
            "/skills/honorific-style", json={"content": VALID_SKILL}, headers=headers
        )
        assert saved.status_code == 200
        assert (
            client.get("/skills/honorific-style", headers=headers).json()["content"]
            == VALID_SKILL
        )

        invalid = client.put(
            "/skills/honorific-style",
            json={"content": "---\nname: other\n---\n\nbody\n"},
            headers=headers,
        )
        assert invalid.status_code == 422
        errors = invalid.json()["detail"]
        assert isinstance(errors, list)
        assert any("name does not match" in error for error in errors)
        # the invalid write must not have clobbered the stored content
        assert (
            client.get("/skills/honorific-style", headers=headers).json()["content"]
            == VALID_SKILL
        )

        deleted = client.delete("/skills/honorific-style", headers=headers)
        assert deleted.status_code == 200
        assert (
            client.get("/skills/honorific-style", headers=headers).status_code == 404
        )
        assert client.get("/skills", headers=headers).json() == []


def test_skills_create_conflict_invalid_name_and_missing_delete(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert (
            client.post("/skills", json={"name": "demo"}, headers=headers).status_code
            == 201
        )
        assert (
            client.post("/skills", json={"name": "demo"}, headers=headers).status_code
            == 409
        )
        bad = client.post("/skills", json={"name": "Bad_Name"}, headers=headers)
        assert bad.status_code == 422
        assert isinstance(bad.json()["detail"], list)
        assert client.delete("/skills/nope", headers=headers).status_code == 404


def test_put_config_rebuilds_skills_manager(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert (
            client.post("/skills", json={"name": "demo"}, headers=headers).status_code
            == 201
        )
        assert client.get("/skills", headers=headers).json()[0]["enabled"] is False

        config = client.get("/config", headers=headers).json()
        config["skills"] = {"demo": {"enabled": True, "confirmed": True}}
        assert client.put("/config", headers=headers, json=config).status_code == 200

        rows = client.get("/skills", headers=headers).json()
        assert rows[0]["enabled"] is True
        assert rows[0]["confirmed"] is True


def test_proposal_approve_applies_config_and_syncs_state(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert (
            client.post("/skills", json={"name": "demo"}, headers=headers).status_code
            == 201
        )
        proposal = proposals.propose_config(
            tmp_path,
            {
                "default_project": "approved",
                "skills": {"demo": {"enabled": True, "confirmed": True}},
            },
            "enable the demo skill",
        )

        rows = client.get("/proposals", headers=headers).json()
        assert [row["id"] for row in rows] == [proposal["id"]]
        assert rows[0]["status"] == "pending"
        assert "default_project" in rows[0]["diff"]

        response = client.post(
            f"/proposals/{proposal['id']}/approve", headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["default_project"] == "approved"

        # disk, GET /config and the in-memory workspace config all converge
        assert load_config(tmp_path).default_project == "approved"
        assert (
            client.get("/config", headers=headers).json()["default_project"]
            == "approved"
        )
        assert client.app.state.workspace.config.default_project == "approved"
        # the skills manager was rebuilt from the approved config
        assert client.get("/skills", headers=headers).json()[0]["enabled"] is True

        assert client.get("/proposals?status=pending", headers=headers).json() == []
        applied = client.get("/proposals?status=applied", headers=headers).json()
        assert [row["id"] for row in applied] == [proposal["id"]]

        # approving an already-applied proposal is a conflict
        again = client.post(f"/proposals/{proposal['id']}/approve", headers=headers)
        assert again.status_code == 409


def test_proposal_reject_and_error_mapping(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        proposal = proposals.propose_config(
            tmp_path, {"default_project": "never"}, "to be rejected"
        )

        rejected = client.post(
            f"/proposals/{proposal['id']}/reject", headers=headers
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"
        assert (
            client.get("/config", headers=headers).json()["default_project"]
            == "default"
        )

        assert (
            client.post(
                f"/proposals/{proposal['id']}/approve", headers=headers
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/proposals/{proposal['id']}/reject", headers=headers
            ).status_code
            == 409
        )
        assert client.post("/proposals/nope/approve", headers=headers).status_code == 404
        assert client.post("/proposals/nope/reject", headers=headers).status_code == 404


def test_proposal_approve_bad_notify_channel_is_422(tmp_path: Path) -> None:
    # A channel like {"type": "carrier_pigeon"} passes CoreConfig validation
    # (channels are plain dicts) and only fails at notifier construction.
    # Approve must pre-flight it like put_config does instead of persisting
    # a config the service cannot boot from.
    with service(tmp_path) as (client, headers, token):
        proposal = proposals.propose_config(
            tmp_path,
            {"notifications": {"channels": [{"type": "carrier_pigeon"}]}},
            "bad channel",
        )
        response = client.post(
            f"/proposals/{proposal['id']}/approve", headers=headers
        )
        assert response.status_code == 422
        assert "carrier_pigeon" in response.json()["detail"]
        # nothing applied: disk, in-memory config and proposal all untouched
        assert load_config(tmp_path).notifications.channels == []
        assert client.app.state.workspace.config.notifications.channels == []
        assert (
            client.get("/proposals?status=pending", headers=headers).json()[0]["id"]
            == proposal["id"]
        )


def test_proposal_approve_invalid_patch_is_422(tmp_path: Path) -> None:
    # A patch can pass validation at propose time yet fail at approve time
    # (config drift). Seed a stored pending proposal whose patch no longer
    # validates and check it maps to 422, not the 409 of the ValueError
    # branch (pydantic's ValidationError subclasses ValueError).
    with service(tmp_path) as (client, headers, token):
        path = tmp_path / "proposals" / "prop-x.json"
        path.write_text(
            json.dumps(
                {
                    "id": "prop-x",
                    "kind": "config",
                    "reason": "drifted",
                    "patch": {"budget": {"task_usd_limit": "lots"}},
                    "diff": "",
                    "status": "pending",
                    "created_at": "t",
                }
            ),
            encoding="utf-8",
        )
        response = client.post("/proposals/prop-x/approve", headers=headers)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)
        # nothing was applied and the proposal stays pending
        assert load_config(tmp_path).budget.task_usd_limit is None
        assert (
            client.get("/proposals?status=pending", headers=headers).json()[0]["id"]
            == "prop-x"
        )
