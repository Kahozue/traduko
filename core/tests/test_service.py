import asyncio
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from traduko.events import Event
from traduko.service.app import create_app
from traduko.service.broadcast import WsBroadcaster


@contextmanager
def service(tmp_path: Path):
    app = create_app(tmp_path)
    token = (tmp_path / "config" / "api-token").read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        yield client, headers, token


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
        }


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
