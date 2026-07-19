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
from traduko.glossary import GlossaryStore
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
            "models": [],
        }


def test_budget_endpoint_aggregates_spend_by_model(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    ledger_dir = tmp_path / "budget"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    rows = [
        {"task_id": "t-1", "project": "p", "kind": "chat", "model": "gpt-4o", "cost_usd": 0.02},
        {"task_id": "t-2", "project": "p", "kind": "chat", "model": "gpt-4o", "cost_usd": 0.03},
        {"task_id": "t-1", "project": "p", "kind": "asr", "model": "whisper-1", "cost_usd": 0.006},
    ]
    with (ledger_dir / f"ledger-{month}.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    with service(tmp_path) as (client, headers, token):
        models = client.get("/budget", headers=headers).json()["models"]
        # Aggregated per model with a call count, ranked by spend descending.
        assert models == [
            {"model": "gpt-4o", "usd": 0.05, "calls": 2},
            {"model": "whisper-1", "usd": 0.006, "calls": 1},
        ]


def test_budget_endpoint_filters_by_time_range(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "budget"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts": "2026-05-10T09:00:00+00:00", "task_id": "t-1", "project": "p",
         "kind": "chat", "model": "gpt-4o", "cost_usd": 0.02},
        {"ts": "2026-06-15T09:00:00+00:00", "task_id": "t-2", "project": "p",
         "kind": "chat", "model": "claude", "cost_usd": 0.05},
    ]
    with (ledger_dir / "ledger-2026-06.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    with service(tmp_path) as (client, headers, token):
        # A window that only covers June excludes the May row from both breakdowns.
        params = {"from": "2026-06-01T00:00:00+00:00", "to": "2026-07-01T00:00:00+00:00"}
        body = client.get("/budget", headers=headers, params=params).json()
        assert body["models"] == [{"model": "claude", "usd": 0.05, "calls": 1}]
        assert [entry["task_id"] for entry in body["tasks"]] == ["t-2"]

        # No bounds -> all-time, both rows counted.
        allrows = client.get("/budget", headers=headers).json()
        assert {m["model"] for m in allrows["models"]} == {"gpt-4o", "claude"}


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


def create_asr_profile(
    tmp_path: Path, name: str, engine: str, *, kind: str = "video"
) -> None:
    (tmp_path / "profiles").mkdir(exist_ok=True)
    (tmp_path / "profiles" / f"{name}.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                f"name: {name}",
                f"kind: {kind}",
                "stages:",
                "  - type: extract_audio",
                "  - type: asr",
                "    params:",
                f"      engine: {engine}",
                "  - type: segment",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def create_reapply_profile(tmp_path: Path, name: str, engine: str) -> None:
    (tmp_path / "profiles").mkdir(exist_ok=True)
    (tmp_path / "profiles" / f"{name}.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                f"name: {name}",
                "kind: video",
                "stages:",
                "  - type: extract_audio",
                "  - type: asr",
                "    params:",
                f"      engine: {engine}",
                "  - type: segment",
                "  - type: translate",
                "    params:",
                "      provider: fake",
                "      target_language: en",
                "  - type: export_subtitles",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def mark_task_completed(client, project: str, task_id: str) -> None:
    from traduko.models import StageStatus, TaskStatus

    store = client.app.state.workspace.store
    record = store.load(project, task_id)
    record.status = TaskStatus.COMPLETED
    for stage in record.stages:
        stage.status = StageStatus.COMPLETED
        stage.error = "old error"
    store.save(record)


def test_create_show_list_roundtrip(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        shown = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        assert shown["status"] == "pending"
        assert shown["profile"] == "subtitle-translate"
        rows = client.get("/tasks", headers=headers).json()
        assert [row["id"] for row in rows] == [task_id]


def test_create_task_sets_domain_and_general_glossaries_without_redundant_proofread(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        store = GlossaryStore(tmp_path)
        general = store.create_table("General", "general")
        video = store.create_table("Video", "video")
        store.create_table("Document", "document")
        disabled = store.create_table("Disabled", "video")
        store.set_enabled(disabled.id, False)

        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "av-default",
            },
            headers=headers,
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["glossary"] == {
            "global_ids": [general.id, video.id],
            "use_task": False,
            "asr_mode": "auto",
        }
        assert "glossary_proofread" not in [stage["type"] for stage in body["stages"]]


def test_create_task_inserts_glossary_proofread_after_unbiased_asr(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        create_asr_profile(tmp_path, "custom-cloud", "cloud_custom")

        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "custom-cloud",
            },
            headers=headers,
        )

        assert response.status_code == 201, response.text
        assert [stage["type"] for stage in response.json()["stages"]] == [
            "extract_audio",
            "asr",
            "glossary_proofread",
            "segment",
        ]


def test_create_document_task_sets_glossary_without_asr_proofread(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        store = GlossaryStore(tmp_path)
        general = store.create_table("General", "general")
        document = store.create_table("Document", "document")
        store.create_table("Video", "video")

        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "novel-translate",
            },
            headers=headers,
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["glossary"]["global_ids"] == [general.id, document.id]
        assert "glossary_proofread" not in [stage["type"] for stage in body["stages"]]


def test_patch_task_glossary_persists_and_rejects_active_task(
    tmp_path: Path, monkeypatch
) -> None:
    with service(tmp_path) as (client, headers, token):
        table = GlossaryStore(tmp_path).create_table("Terms", "general")
        task_id = create_task(client, headers, tmp_path)
        url = f"/tasks/default/{task_id}"
        glossary = {
            "global_ids": [table.id],
            "use_task": True,
            "asr_mode": "force",
        }

        response = client.patch(url, json={"glossary": glossary}, headers=headers)

        assert response.status_code == 200, response.text
        assert response.json()["glossary"] == glossary
        assert client.get(url, headers=headers).json()["glossary"] == glossary

        monkeypatch.setattr(client.app.state.worker, "is_active", lambda p, t: True)
        blocked = client.patch(
            url,
            json={
                "glossary": {
                    "global_ids": [],
                    "use_task": False,
                    "asr_mode": "off",
                }
            },
            headers=headers,
        )
        assert blocked.status_code == 409


def test_task_glossary_entries_round_trip(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        url = f"/tasks/default/{task_id}/glossary/entries"
        entries = [
            {
                "source": "Traduko",
                "target": "特拉杜科",
                "notes": "product",
                "category": "名稱",
            }
        ]

        saved = client.put(url, json={"entries": entries}, headers=headers)

        assert saved.status_code == 200, saved.text
        assert saved.json() == {"saved": True, "count": 1}
        assert client.get(url, headers=headers).json() == {"entries": entries}
        assert (
            tmp_path
            / "projects"
            / "default"
            / "tasks"
            / task_id
            / "glossary.csv"
        ).exists()


def test_reapply_asr_inserts_forced_proofread_and_resets_from_asr(
    tmp_path: Path, monkeypatch
) -> None:
    with service(tmp_path) as (client, headers, token):
        create_reapply_profile(tmp_path, "reapply-asr", "faster_whisper")
        task_id = create_task(client, headers, tmp_path, profile="reapply-asr")
        url = f"/tasks/default/{task_id}"
        assert client.patch(
            url,
            json={
                "glossary": {
                    "global_ids": [],
                    "use_task": False,
                    "asr_mode": "force",
                }
            },
            headers=headers,
        ).status_code == 200
        mark_task_completed(client, "default", task_id)
        queued: list[tuple[str, str]] = []
        monkeypatch.setattr(
            client.app.state.worker,
            "enqueue",
            lambda project, current_id: not queued.append((project, current_id)),
        )

        response = client.post(
            f"{url}/glossary/reapply", json={"mode": "asr"}, headers=headers
        )

        assert response.status_code == 202, response.text
        assert response.json() == {"queued": True, "reset_from": "asr"}
        shown = client.get(url, headers=headers).json()
        types = [stage["type"] for stage in shown["stages"]]
        assert types == [
            "extract_audio",
            "asr",
            "glossary_proofread",
            "segment",
            "translate",
            "export_subtitles",
        ]
        assert shown["stages"][0]["status"] == "completed"
        assert all(stage["status"] == "pending" for stage in shown["stages"][1:])
        assert all(stage["error"] is None for stage in shown["stages"][1:])
        assert shown["status"] == "pending"
        assert queued == [("default", task_id)]


def test_reapply_proofread_inserts_stage_without_resetting_asr(
    tmp_path: Path, monkeypatch
) -> None:
    with service(tmp_path) as (client, headers, token):
        create_reapply_profile(tmp_path, "reapply-proof", "faster_whisper")
        task_id = create_task(client, headers, tmp_path, profile="reapply-proof")
        mark_task_completed(client, "default", task_id)
        monkeypatch.setattr(client.app.state.worker, "enqueue", lambda p, t: True)

        response = client.post(
            f"/tasks/default/{task_id}/glossary/reapply",
            json={"mode": "proofread"},
            headers=headers,
        )

        assert response.status_code == 202, response.text
        assert response.json()["reset_from"] == "glossary_proofread"
        shown = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        by_type = {stage["type"]: stage for stage in shown["stages"]}
        assert by_type["asr"]["status"] == "completed"
        assert by_type["glossary_proofread"]["status"] == "pending"
        assert by_type["segment"]["status"] == "pending"


@pytest.mark.parametrize(
    ("profile", "expected_type"),
    [("subtitle-translate", "translate"), ("novel-translate", "translate_chunks")],
)
def test_reapply_translate_resets_first_translation_stage_only(
    tmp_path: Path, monkeypatch, profile: str, expected_type: str
) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile=profile)
        mark_task_completed(client, "default", task_id)
        monkeypatch.setattr(client.app.state.worker, "enqueue", lambda p, t: True)

        response = client.post(
            f"/tasks/default/{task_id}/glossary/reapply",
            json={"mode": "translate"},
            headers=headers,
        )

        assert response.status_code == 202, response.text
        assert response.json()["reset_from"] == expected_type
        stages = client.get(
            f"/tasks/default/{task_id}", headers=headers
        ).json()["stages"]
        reset_index = next(
            index for index, stage in enumerate(stages) if stage["type"] == expected_type
        )
        assert all(stage["status"] == "completed" for stage in stages[:reset_index])
        assert all(stage["status"] == "pending" for stage in stages[reset_index:])


def test_reapply_rejects_missing_stage_invalid_mode_and_active_task(
    tmp_path: Path, monkeypatch
) -> None:
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "noop-only", ["noop"])
        task_id = create_task(client, headers, tmp_path, profile="noop-only")
        url = f"/tasks/default/{task_id}/glossary/reapply"

        assert client.post(
            url, json={"mode": "asr"}, headers=headers
        ).status_code == 409
        assert client.post(
            url, json={"mode": "proofread"}, headers=headers
        ).status_code == 409
        assert client.post(
            url, json={"mode": "translate"}, headers=headers
        ).status_code == 409
        assert client.post(
            url, json={"mode": "invalid"}, headers=headers
        ).status_code == 422

        monkeypatch.setattr(client.app.state.worker, "is_active", lambda p, t: True)
        active = client.post(url, json={"mode": "translate"}, headers=headers)
        assert active.status_code == 409


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


def test_rerun_completed_task_requeues(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        client.post(f"/tasks/default/{task_id}/run", headers=headers)
        wait_completed(client, headers, "default", task_id)
        response = client.post(f"/tasks/default/{task_id}/rerun", headers=headers)
        assert response.status_code == 202, response.text
        assert response.json() == {"queued": True}
        shown = wait_completed(client, headers, "default", task_id)
        assert shown["status"] == "completed"


def test_rerun_rejects_non_completed_task(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        denied = client.post(f"/tasks/default/{task_id}/rerun", headers=headers)
        assert denied.status_code == 409
        assert "pending" in denied.json()["detail"]


def test_rerun_gates_on_preflight_then_skip_resets(tmp_path: Path) -> None:
    write_passthrough(tmp_path)
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="passthrough")
        client.post(f"/tasks/default/{task_id}/run", headers=headers)
        wait_completed(client, headers, "default", task_id)
        (tmp_path / "in.srt").unlink()

        denied = client.post(f"/tasks/default/{task_id}/rerun", headers=headers)
        assert denied.status_code == 409
        assert denied.json()["detail"]["checks"][0]["name"] == "input"
        # A failed rerun preflight leaves the completed task untouched, so the
        # client can retry the same endpoint with skip_preflight.
        shown = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        assert shown["status"] == "completed"
        assert all(s["status"] == "completed" for s in shown["stages"])

        forced = client.post(
            f"/tasks/default/{task_id}/rerun",
            json={"skip_preflight": True},
            headers=headers,
        )
        assert forced.status_code == 202
        assert (
            wait_completed(client, headers, "default", task_id)["status"] == "completed"
        )


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


def test_delete_orphan_index_row(tmp_path: Path) -> None:
    import shutil

    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        # Simulate a task whose directory vanished but whose index row remains
        # (e.g. an interrupted delete): it still shows up in the list, so the
        # user must be able to clear it.
        shutil.rmtree(tmp_path / "projects" / "default" / "tasks" / task_id)
        assert [t["id"] for t in client.get("/tasks", headers=headers).json()] == [task_id]
        assert client.delete(f"/tasks/default/{task_id}", headers=headers).status_code == 200
        assert client.get("/tasks", headers=headers).json() == []


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


def test_force_delete_removes_active_task(tmp_path: Path) -> None:
    ServiceGateStage.gate = threading.Event()
    ServiceGateStage.started = threading.Event()
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "gated", ["svc-gate", "noop"])
        task_id = create_task(client, headers, tmp_path, profile="gated")
        url = f"/tasks/default/{task_id}"
        assert client.post(f"{url}/run", headers=headers).status_code == 202
        assert ServiceGateStage.started.wait(timeout=5)
        # Without force the running task is protected.
        assert client.delete(url, headers=headers).status_code == 409
        # force stops the task and removes it in one call.
        assert client.delete(f"{url}?force=true", headers=headers).status_code == 200
        assert client.get(url, headers=headers).status_code == 404
        assert not (tmp_path / "projects" / "default" / "tasks" / task_id).exists()
        # Release the gate so the worker thread can unwind cleanly.
        ServiceGateStage.gate.set()


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
            "demo": {
                "transport": "stdio",
                "command": "demo-cmd",
                "enabled": True,
                "confirmed": True,
            }
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


def test_put_skill_content_change_resets_confirmation(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert (
            client.post("/skills", json={"name": "demo"}, headers=headers).status_code
            == 201
        )
        config = client.get("/config", headers=headers).json()
        config["skills"] = {"demo": {"enabled": True, "confirmed": True}}
        assert client.put("/config", headers=headers, json=config).status_code == 200

        content = client.get("/skills/demo", headers=headers).json()["content"]

        # Saving identical content keeps the confirmation.
        saved = client.put("/skills/demo", json={"content": content}, headers=headers)
        assert saved.json() == {"saved": True, "confirmation_reset": False}
        assert client.get("/skills", headers=headers).json()[0]["confirmed"] is True

        # Changing the body reopens the gate: the confirmation covered the
        # reviewed content, not the name.
        changed = content.replace(
            "Write the skill instructions here.", "Always use formal tone."
        )
        saved = client.put("/skills/demo", json={"content": changed}, headers=headers)
        assert saved.json() == {"saved": True, "confirmation_reset": True}
        row = client.get("/skills", headers=headers).json()[0]
        assert row["enabled"] is True
        assert row["confirmed"] is False
        # The reset is persisted, not just held in memory.
        assert load_config(tmp_path).skills["demo"].confirmed is False


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
                # enabled only: `confirmed` cannot travel through the
                # proposal channel (settings-panel-only safety gate).
                "skills": {"demo": {"enabled": True}},
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


# --- assistant --------------------------------------------------------------


def configure_scripted_assistant(client, headers, responses: list[str]) -> None:
    """Point the running service's default llm provider at the scripted
    provider so /assistant/message runs deterministically, the same way
    test_assistant.py's scripted_ws drives run_assistant_message directly."""
    config = client.get("/config", headers=headers).json()
    config["llm_providers"]["default"] = {"type": "scripted", "responses": responses}
    response = client.put("/config", headers=headers, json=config)
    assert response.status_code == 200, response.text


def test_assistant_history_is_empty_list_before_any_message(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/assistant/history", headers=headers)
        assert response.status_code == 200
        assert response.json() == []


def test_assistant_attachment_saves_pasted_image_and_returns_path(
    tmp_path: Path,
) -> None:
    import base64 as b64

    with service(tmp_path) as (client, headers, token):
        payload = b"\x89PNG-clipboard-bytes"
        response = client.post(
            "/assistant/attachments",
            headers=headers,
            json={
                "mime": "image/png",
                "data_base64": b64.b64encode(payload).decode("ascii"),
            },
        )
        assert response.status_code == 201, response.text
        path = Path(response.json()["path"])
        assert path.is_absolute()
        assert path.parent == tmp_path / "assistant" / "attachments"
        assert path.suffix == ".png"
        assert path.read_bytes() == payload


def test_assistant_attachment_rejects_bad_mime_and_bad_base64(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/assistant/attachments",
            headers=headers,
            json={"mime": "application/pdf", "data_base64": "aGk="},
        )
        assert response.status_code == 422
        response = client.post(
            "/assistant/attachments",
            headers=headers,
            json={"mime": "image/png", "data_base64": "not base64!!"},
        )
        assert response.status_code == 422


def test_assistant_message_without_llm_provider_is_409(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/assistant/message", headers=headers, json={"text": "hi"}
        )
        assert response.status_code == 409
        assert "llm_providers" in response.json()["detail"]


def test_assistant_message_blank_text_is_422(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/assistant/message", headers=headers, json={"text": "   "}
        )
        assert response.status_code == 422


def test_assistant_message_provider_failure_is_502_with_raw_detail(
    tmp_path: Path,
) -> None:
    # An empty scripted response list makes the provider raise LLMError on the
    # first turn (a runtime bad-key / unknown-model stand-in). The endpoint
    # must surface it as 502 with the raw message, not a generic 500, so the
    # panel can classify it into readable wording.
    with service(tmp_path) as (client, headers, token):
        configure_scripted_assistant(client, headers, [])
        response = client.post(
            "/assistant/message", headers=headers, json={"text": "hi"}
        )
        assert response.status_code == 502
        assert "scripted provider ran out of responses" in response.json()["detail"]


def test_assistant_message_full_flow_and_history_persists(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        configure_scripted_assistant(
            client, headers, ['{"done": true, "summary": "hello there"}']
        )

        response = client.post(
            "/assistant/message", headers=headers, json={"text": "hi assistant"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["reply"] == "hello there"
        assert body["converged"] is True
        assert body["reason"] == "done"
        assert body["proposal_ids"] == []
        assert [m["role"] for m in body["history"]] == ["user", "assistant"]
        assert body["history"][0]["text"] == "hi assistant"
        assert body["history"][1]["text"] == "hello there"

        # persists across a second GET, independent of the POST response
        again = client.get("/assistant/history", headers=headers)
        assert again.status_code == 200
        assert again.json() == body["history"]


def test_assistant_clear_empties_history_but_keeps_run_records(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        configure_scripted_assistant(
            client, headers, ['{"done": true, "summary": "ok"}']
        )
        client.post("/assistant/message", headers=headers, json={"text": "hi"})
        assert client.get("/assistant/history", headers=headers).json() != []
        run_files = sorted((tmp_path / "assistant" / "runs").glob("*.jsonl"))
        assert len(run_files) == 1

        response = client.post("/assistant/clear", headers=headers)
        assert response.status_code == 200

        assert client.get("/assistant/history", headers=headers).json() == []
        assert sorted((tmp_path / "assistant" / "runs").glob("*.jsonl")) == run_files


def test_provider_test_endpoint_reports_missing_model(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/config/providers/test",
            headers=headers,
            json={"config": {"type": "fake"}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "model" in body["error"]


def test_provider_test_endpoint_ok_for_reachable_fake(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/config/providers/test",
            headers=headers,
            json={"config": {"type": "fake", "model": "fake-model"}},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}


def test_provider_test_endpoint_classifies_unknown_type(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/config/providers/test",
            headers=headers,
            json={"config": {"type": "nope", "model": "m"}},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "nope" in body["error"]


def test_skills_import_creates_from_frontmatter(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/skills/import", json={"content": VALID_SKILL}, headers=headers
        )
        assert response.status_code == 201, response.text
        assert response.json() == {"created": "honorific-style"}
        rows = client.get("/skills", headers=headers).json()
        assert [row["name"] for row in rows] == ["honorific-style"]
        # Imported skills land unconfirmed: the confirmation gate still applies.
        assert rows[0]["confirmed"] is False


def test_skills_import_rejects_invalid_and_duplicate(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        bad = client.post(
            "/skills/import", json={"content": "not a skill"}, headers=headers
        )
        assert bad.status_code == 422
        assert isinstance(bad.json()["detail"], list)
        client.post("/skills/import", json={"content": VALID_SKILL}, headers=headers)
        dup = client.post(
            "/skills/import", json={"content": VALID_SKILL}, headers=headers
        )
        assert dup.status_code == 409


def test_assistant_sessions_list_create_activate_delete(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        configure_scripted_assistant(
            client, headers, ['{"done": true, "summary": "one"}']
        )
        client.post("/assistant/message", headers=headers, json={"text": "first talk"})

        rows = client.get("/assistant/sessions", headers=headers).json()
        assert len(rows) == 1
        assert rows[0]["title"] == "first talk"
        first_id = rows[0]["id"]

        created = client.post("/assistant/sessions", headers=headers)
        assert created.status_code == 201
        new_id = created.json()["id"]
        # New session is now active and empty.
        assert client.get("/assistant/history", headers=headers).json() == []

        # Reactivate the first and its history returns.
        client.post(f"/assistant/sessions/{first_id}/activate", headers=headers)
        assert client.get("/assistant/history", headers=headers).json() != []

        # Archive then delete the new one.
        archived = client.patch(
            f"/assistant/sessions/{new_id}", headers=headers, json={"archived": True}
        )
        assert archived.status_code == 200
        deleted = client.delete(f"/assistant/sessions/{new_id}", headers=headers)
        assert deleted.status_code == 200
        remaining = [row["id"] for row in client.get("/assistant/sessions", headers=headers).json()]
        assert new_id not in remaining


def test_assistant_edit_resend_truncates_and_reruns(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        configure_scripted_assistant(
            client,
            headers,
            [
                '{"done": true, "summary": "reply one"}',
                '{"done": true, "summary": "reply two"}',
            ],
        )
        client.post("/assistant/message", headers=headers, json={"text": "hello v1"})
        # Edit the first user message (index 0): drop everything from there and
        # rerun with the corrected text.
        resent = client.post(
            "/assistant/message",
            headers=headers,
            json={"text": "hello v2", "edit_index": 0},
        )
        assert resent.status_code == 200, resent.text
        history = resent.json()["history"]
        # The v1 turn (user + reply) was dropped at index 0 before the rerun,
        # so exactly one user/assistant pair remains, carrying the edited text.
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["text"] == "hello v2"


def test_assistant_message_records_attached_images(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        configure_scripted_assistant(
            client, headers, ['{"done": true, "summary": "saw it"}']
        )
        response = client.post(
            "/assistant/message",
            headers=headers,
            json={"text": "check this", "images": ["/tmp/shot.png"]},
        )
        assert response.status_code == 200, response.text
        history = response.json()["history"]
        assert history[0]["images"] == ["/tmp/shot.png"]


def test_assistant_session_unknown_id_is_404(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert (
            client.get("/assistant/sessions/nope", headers=headers).status_code == 404
        )
        assert (
            client.post(
                "/assistant/sessions/nope/activate", headers=headers
            ).status_code
            == 404
        )


def test_profiles_detailed_classifies_kinds(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        rows = client.get("/profiles/detailed", headers=headers).json()
        by_name = {row["name"]: row["kind"] for row in rows}
        assert by_name["subtitle-translate"] == "video"
        assert by_name["av-default"] == "video"
        assert by_name["novel-translate"] == "document"
        assert by_name["translate-pdf"] == "document"
        # Stage types ride along so the app can tell dub pipelines apart.
        stages = {row["name"]: row["stages"] for row in rows}
        assert "tts_synthesize" in stages["av-dub"]
        assert "tts_synthesize" not in stages["subtitle-translate"]


def test_dubbing_status_install_and_test_flow(tmp_path: Path) -> None:
    from traduko.dubbing.setup import DubbingManager

    def fake_install(target_dir: Path, python: str) -> None:
        bin_dir = target_dir / "venv" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "python").write_bytes(b"x" * (2 * 1024 * 1024))
        (target_dir / ".installed").write_text("{}", encoding="utf-8")

    with service(tmp_path) as (client, headers, token):
        client.app.state.dubbing = DubbingManager(
            tmp_path,
            installer=fake_install,
            probe=lambda candidate: {"python3.11": (3, 11, 5)}.get(candidate),
            engine_probe=lambda target: {"ok": True, "torch": "2.5.0", "mps": True},
        )
        status = client.get("/dubbing/status", headers=headers).json()
        assert status["python"] == "python3.11"
        assert status["installed"] is False

        blocked = client.post("/dubbing/test", headers=headers)
        assert blocked.status_code == 409

        started = client.post("/dubbing/install", headers=headers)
        assert started.status_code == 202

        deadline = time.monotonic() + 5
        status = client.get("/dubbing/status", headers=headers).json()
        while time.monotonic() < deadline and status["state"] != "done":
            status = client.get("/dubbing/status", headers=headers).json()
        assert status["installed"] is True
        assert status["installed_mb"] > 0

        result = client.post("/dubbing/test", headers=headers).json()
        assert result == {"ok": True, "torch": "2.5.0", "mps": True}


def test_dubbing_install_without_python_is_409(tmp_path: Path) -> None:
    from traduko.dubbing.setup import DubbingManager

    with service(tmp_path) as (client, headers, token):
        client.app.state.dubbing = DubbingManager(
            tmp_path, installer=lambda t, p: None, probe=lambda candidate: None
        )
        response = client.post("/dubbing/install", headers=headers)
        assert response.status_code == 409
        assert "python" in response.json()["detail"].lower()

def test_pdf_status_install_and_test_flow(tmp_path: Path) -> None:
    from traduko.pdfengine.setup import PdfManager

    def fake_install(target_dir: Path, python: str) -> None:
        bin_dir = target_dir / "venv" / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "python").write_bytes(b"x" * (2 * 1024 * 1024))
        (target_dir / ".installed").write_text("{}", encoding="utf-8")

    with service(tmp_path) as (client, headers, token):
        client.app.state.pdf = PdfManager(
            tmp_path,
            installer=fake_install,
            probe=lambda candidate: {"python3.12": (3, 12, 3)}.get(candidate),
            engine_probe=lambda target: {"ok": True, "version": "2.9.0"},
        )
        status = client.get("/pdf/status", headers=headers).json()
        assert status["python"] == "python3.12"
        assert status["installed"] is False

        blocked = client.post("/pdf/test", headers=headers)
        assert blocked.status_code == 409

        started = client.post("/pdf/install", headers=headers)
        assert started.status_code == 202

        deadline = time.monotonic() + 5
        status = client.get("/pdf/status", headers=headers).json()
        while time.monotonic() < deadline and status["state"] != "done":
            status = client.get("/pdf/status", headers=headers).json()
        assert status["installed"] is True

        result = client.post("/pdf/test", headers=headers).json()
        assert result == {"ok": True, "version": "2.9.0"}


def test_pdf_install_without_python_is_409(tmp_path: Path) -> None:
    from traduko.pdfengine.setup import PdfManager

    with service(tmp_path) as (client, headers, token):
        client.app.state.pdf = PdfManager(
            tmp_path, installer=lambda t, p: None, probe=lambda candidate: None
        )
        response = client.post("/pdf/install", headers=headers)
        assert response.status_code == 409
        assert "python" in response.json()["detail"].lower()


def test_provider_test_endpoint_accepts_native_types(tmp_path: Path) -> None:
    """anthropic/gemini types flow through create_llm; an unreachable
    endpoint comes back as data (ok: false), never a 500."""
    with service(tmp_path) as (client, headers, token):
        for provider_type in ("anthropic", "gemini"):
            response = client.post(
                "/config/providers/test",
                headers=headers,
                json={
                    "config": {
                        "type": provider_type,
                        "base_url": "http://127.0.0.1:9/x",
                        "model": "m",
                        "max_retries": 0,
                        "backoff_base": 0.0,
                    }
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is False
            assert "failed" in body["error"]


def test_create_task_with_model_override(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "subtitle-translate",
                "provider": "deepseek",
                "model": "deepseek-chat",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        stages = response.json()["stages"]
        by_type = {stage["type"]: stage for stage in stages}
        assert by_type["translate"]["params"]["provider"] == "deepseek"
        assert by_type["translate"]["params"]["model"] == "deepseek-chat"
        assert by_type["proofread"]["params"]["provider"] == "deepseek"
        assert "provider" not in by_type["ingest_subtitle"]["params"]


def test_patch_task_model_override_and_reset(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path)
        url = f"/tasks/default/{task_id}"
        patched = client.patch(
            url, json={"provider": "glm", "model": "glm-4"}, headers=headers
        )
        assert patched.status_code == 200
        by_type = {s["type"]: s for s in patched.json()["stages"]}
        assert by_type["translate"]["params"]["provider"] == "glm"
        assert by_type["translate"]["params"]["model"] == "glm-4"
        # Reset: empty strings restore the follow-default state.
        reset = client.patch(url, json={"provider": "", "model": ""}, headers=headers)
        assert reset.status_code == 200
        by_type = {s["type"]: s for s in reset.json()["stages"]}
        assert by_type["translate"]["params"]["provider"] == "fake"
        assert "model" not in by_type["translate"]["params"]
        # Persisted, not just echoed.
        shown = client.get(url, headers=headers).json()
        by_type = {s["type"]: s for s in shown["stages"]}
        assert by_type["proofread"]["params"]["provider"] == "fake"


def test_patch_model_override_rejected_while_active(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "gated", ["svc-gate"])
        ServiceGateStage.gate.clear()
        ServiceGateStage.started.clear()
        response = client.post(
            "/tasks",
            json={"input_path": str(make_input(tmp_path)), "profile": "gated"},
            headers=headers,
        )
        task_id = response.json()["id"]
        url = f"/tasks/default/{task_id}"
        assert client.post(f"{url}/run", headers=headers).status_code == 202
        assert ServiceGateStage.started.wait(timeout=5)
        denied = client.patch(url, json={"provider": "glm"}, headers=headers)
        assert denied.status_code == 409
        ServiceGateStage.gate.set()
        wait_completed(client, headers, "default", task_id)


def test_asr_engines_endpoint_lists_catalog_and_macos_status(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/asr/engines", headers=headers)
        assert response.status_code == 200
        body = response.json()
        ids = [engine["id"] for engine in body["engines"]]
        assert "faster_whisper" in ids
        assert "openai_gpt4o" in ids
        gpt4o = next(e for e in body["engines"] if e["id"] == "openai_gpt4o")
        assert gpt4o["timestamps"] is False
        assert "macos" in body
        assert "available" in body["macos"]
        assert body["cloud_key_present"] is False


def test_asr_macos_assets_endpoint_gates_unavailable(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        # On an unavailable helper (non-macOS CI or uncompiled), the assets
        # endpoint refuses instead of spawning a doomed download.
        response = client.post(
            "/asr/macos/assets", json={"locale": "zh-TW"}, headers=headers
        )
        assert response.status_code in (202, 409)


def test_asr_test_routes_by_engine(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/asr/test", json={"engine": "openai_whisper"}, headers=headers
        )
        assert response.status_code == 200
        body = response.json()
        # No key configured: the cloud test fails with a clear error.
        assert body["ok"] is False
        assert "key" in (body.get("error") or "")


def test_create_and_patch_asr_engine(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "with-asr", ["extract_audio", "asr", "export_transcript"])
        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "with-asr",
                "asr_engine": "openai_gpt4o",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        task = response.json()
        by_type = {s["type"]: s for s in task["stages"]}
        assert by_type["asr"]["params"]["engine"] == "openai_gpt4o"
        url = f"/tasks/default/{task['id']}"
        patched = client.patch(url, json={"asr_engine": "openai_whisper"}, headers=headers)
        assert patched.status_code == 200
        by_type = {s["type"]: s for s in patched.json()["stages"]}
        assert by_type["asr"]["params"]["engine"] == "openai_whisper"
        # Empty string removes the override, restoring the profile default.
        reset = client.patch(url, json={"asr_engine": ""}, headers=headers)
        by_type = {s["type"]: s for s in reset.json()["stages"]}
        assert "engine" not in by_type["asr"]["params"]


def test_create_and_patch_voice_mode(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        create_profile(
            tmp_path,
            "with-dub",
            ["diarize", "tts_synthesize", "align_duration", "mix_audio"],
        )
        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "with-dub",
                "voice_mode": "preview",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        task = response.json()
        by_type = {s["type"]: s for s in task["stages"]}
        for stage_type in ("diarize", "tts_synthesize", "align_duration"):
            assert by_type[stage_type]["params"]["voice_mode"] == "preview"
        assert "voice_mode" not in by_type["mix_audio"]["params"]

        url = f"/tasks/default/{task['id']}"
        patched = client.patch(
            url,
            json={"voice_mode": "design", "voice_instruction": "沉穩男聲"},
            headers=headers,
        )
        assert patched.status_code == 200
        by_type = {s["type"]: s for s in patched.json()["stages"]}
        assert by_type["diarize"]["params"]["voice_mode"] == "design"
        assert by_type["tts_synthesize"]["params"]["voice_instruction"] == "沉穩男聲"
        assert by_type["align_duration"]["params"]["voice_instruction"] == "沉穩男聲"
        # The instruction stays off the diarize stage, which never speaks.
        assert "voice_instruction" not in by_type["diarize"]["params"]

        # Empty strings reset to the clone default and clear the instruction.
        reset = client.patch(
            url, json={"voice_mode": "", "voice_instruction": ""}, headers=headers
        )
        by_type = {s["type"]: s for s in reset.json()["stages"]}
        assert "voice_mode" not in by_type["diarize"]["params"]
        assert "voice_instruction" not in by_type["tts_synthesize"]["params"]


def test_voice_mode_rejects_unknown_values(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "dub-v", ["tts_synthesize"])
        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "dub-v",
                "voice_mode": "loud",
            },
            headers=headers,
        )
        assert response.status_code == 422
        assert "voice_mode" in response.json()["detail"]


def test_dubbing_model_endpoints(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        app = client.app
        # Inject fakes so no network or real HF cache is touched.
        app.state.dubbing._model_info = lambda repo: 4960.0
        app.state.dubbing._model_downloader = lambda repo: None
        app.state.dubbing._model_cache_dir = tmp_path / "hf"
        status = client.get("/dubbing/model/status", headers=headers).json()
        assert status["repo"] == "openbmb/VoxCPM2"
        assert status["cached"] is False
        response = client.post("/dubbing/model/download", headers=headers)
        assert response.status_code == 202
        for _ in range(100):
            status = client.get("/dubbing/model/status", headers=headers).json()
            if status["state"] in ("done", "error"):
                break
            time.sleep(0.01)
        assert status["state"] == "done"


def test_mcp_candidates_endpoint(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.get("/mcp/candidates", headers=headers)
        assert response.status_code == 200
        names = [entry["name"] for entry in response.json()]
        assert names == ["fetch", "memory", "filesystem", "playwright"]


# --- glossary endpoints (v3_5-02) ------------------------------------------


def test_glossaries_require_token(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert client.get("/glossaries").status_code == 401


def test_glossary_crud_full_flow(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        created = client.post(
            "/glossaries",
            json={"name": "Anime Terms", "domain": "video"},
            headers=headers,
        )
        assert created.status_code == 201
        gid = created.json()["id"]

        rows = client.get("/glossaries", headers=headers).json()
        assert [r["id"] for r in rows] == [gid]
        assert rows[0]["entry_count"] == 0
        assert rows[0]["enabled"] is True

        saved = client.put(
            f"/glossaries/{gid}/entries",
            json={
                "entries": [
                    {"source": "Kirito", "target": "桐人", "notes": "", "category": "人名"}
                ]
            },
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.json() == {"saved": True, "count": 1}

        detail = client.get(f"/glossaries/{gid}", headers=headers).json()
        assert detail["entries"][0]["source"] == "Kirito"
        assert detail["entries"][0]["category"] == "人名"
        assert client.get("/glossaries", headers=headers).json()[0]["entry_count"] == 1

        client.patch(f"/glossaries/{gid}", json={"enabled": False}, headers=headers)
        assert client.get("/glossaries", headers=headers).json()[0]["enabled"] is False
        renamed = client.patch(
            f"/glossaries/{gid}", json={"name": "Renamed"}, headers=headers
        )
        assert renamed.json()["name"] == "Renamed"

        assert client.get("/glossaries?domain=audio", headers=headers).json() == []
        assert len(client.get("/glossaries?domain=video", headers=headers).json()) == 1

        assert client.delete(f"/glossaries/{gid}", headers=headers).json() == {
            "deleted": True
        }
        assert client.get("/glossaries", headers=headers).json() == []


def test_glossary_unknown_id_returns_404(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert client.get("/glossaries/nope", headers=headers).status_code == 404
        assert (
            client.patch(
                "/glossaries/nope", json={"name": "x"}, headers=headers
            ).status_code
            == 404
        )
        assert client.delete("/glossaries/nope", headers=headers).status_code == 404
        assert (
            client.put(
                "/glossaries/nope/entries", json={"entries": []}, headers=headers
            ).status_code
            == 404
        )


def test_glossary_create_validation(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        assert (
            client.post(
                "/glossaries", json={"name": "  ", "domain": "video"}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/glossaries", json={"name": "X", "domain": "bogus"}, headers=headers
            ).status_code
            == 422
        )


def test_glossary_import_csv_and_bad_format(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        content = "source,target,notes,category\r\nKirito,桐人,,人名\r\n"
        imported = client.post(
            "/glossaries/import",
            json={"name": "Imp", "domain": "general", "content": content, "format": "csv"},
            headers=headers,
        )
        assert imported.status_code == 201
        assert imported.json()["entry_count"] == 1
        gid = imported.json()["id"]
        assert (
            client.get(f"/glossaries/{gid}", headers=headers).json()["entries"][0][
                "source"
            ]
            == "Kirito"
        )
        assert (
            client.post(
                "/glossaries/import",
                json={"name": "Y", "domain": "general", "content": "x", "format": "xml"},
                headers=headers,
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/glossaries/import",
                json={
                    "name": "Z",
                    "domain": "general",
                    "content": "{not json",
                    "format": "json",
                },
                headers=headers,
            ).status_code
            == 422
        )


def test_glossary_export_csv_and_json(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        gid = client.post(
            "/glossaries", json={"name": "Exp", "domain": "general"}, headers=headers
        ).json()["id"]
        client.put(
            f"/glossaries/{gid}/entries",
            json={
                "entries": [
                    {"source": "Kirito", "target": "桐人", "notes": "", "category": ""}
                ]
            },
            headers=headers,
        )
        csv_resp = client.get(f"/glossaries/{gid}/export?format=csv", headers=headers)
        assert csv_resp.status_code == 200
        assert csv_resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in csv_resp.headers["content-disposition"]
        assert "Kirito" in csv_resp.text

        json_resp = client.get(f"/glossaries/{gid}/export?format=json", headers=headers)
        assert json_resp.headers["content-type"].startswith("application/json")
        assert json.loads(json_resp.text)["entries"][0]["source"] == "Kirito"

        assert (
            client.get("/glossaries/nope/export", headers=headers).status_code == 404
        )


# --- pipeline switches (v3_5-04) --------------------------------------------


def test_patch_switches_translate_off_skips_group_and_leaves_rest(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="audio-translate")
        url = f"/tasks/default/{task_id}"

        response = client.patch(
            f"{url}/switches", json={"translate": False}, headers=headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["switches"]["translate"] is False
        by_type = {stage["type"]: stage for stage in body["stages"]}
        assert by_type["translate"]["status"] == "skipped"
        assert by_type["proofread"]["status"] == "skipped"
        assert by_type["export_subtitles"]["status"] == "skipped"
        assert by_type["extract_audio"]["status"] == "pending"
        assert by_type["asr"]["status"] == "pending"
        assert by_type["export_transcript"]["status"] == "pending"
        shown = client.get(url, headers=headers).json()
        assert shown["switches"]["translate"] is False
        assert shown["switches"]["dub"] is None


def test_patch_switches_reenable_marks_skipped_back_pending(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="audio-translate")
        url = f"/tasks/default/{task_id}/switches"
        assert client.patch(
            url, json={"translate": False}, headers=headers
        ).status_code == 200

        response = client.patch(url, json={"translate": True}, headers=headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["switches"]["translate"] is True
        by_type = {stage["type"]: stage for stage in body["stages"]}
        assert by_type["translate"]["status"] == "pending"
        assert by_type["proofread"]["status"] == "pending"
        assert by_type["export_subtitles"]["status"] == "pending"


def test_patch_switches_off_keeps_completed_then_reenable_reruns(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="audio-translate")
        mark_task_completed(client, "default", task_id)
        url = f"/tasks/default/{task_id}"

        off = client.patch(
            f"{url}/switches", json={"translate": False}, headers=headers
        ).json()
        by_type = {stage["type"]: stage for stage in off["stages"]}
        assert by_type["translate"]["status"] == "skipped"
        assert by_type["asr"]["status"] == "completed"
        assert off["status"] == "completed"

        on = client.patch(
            f"{url}/switches", json={"translate": True}, headers=headers
        ).json()
        by_type = {stage["type"]: stage for stage in on["stages"]}
        assert by_type["translate"]["status"] == "pending"
        assert by_type["asr"]["status"] == "completed"
        assert on["status"] == "pending"


def test_patch_switches_rejects_active_task_and_empty_body(
    tmp_path: Path, monkeypatch
) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="audio-translate")
        url = f"/tasks/default/{task_id}/switches"

        assert client.patch(url, json={}, headers=headers).status_code == 422

        monkeypatch.setattr(client.app.state.worker, "is_active", lambda p, t: True)
        blocked = client.patch(url, json={"translate": False}, headers=headers)
        assert blocked.status_code == 409


def test_patch_switches_translate_is_audio_only(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="av-default")
        url = f"/tasks/default/{task_id}/switches"

        rejected = client.patch(url, json={"translate": False}, headers=headers)

        assert rejected.status_code == 422
        # diarize stays available on video tasks (av-dub has the stage).
        dub_id = create_task(client, headers, tmp_path, profile="av-dub")
        ok = client.patch(
            f"/tasks/default/{dub_id}/switches",
            json={"diarize": False},
            headers=headers,
        )
        assert ok.status_code == 200, ok.text
        by_type = {stage["type"]: stage for stage in ok.json()["stages"]}
        assert by_type["diarize"]["status"] == "skipped"
        assert by_type["translate"]["status"] == "pending"


def test_task_dub_text_override_create_update_and_validation(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        response = client.post(
            "/tasks",
            json={
                "input_path": str(make_input(tmp_path)),
                "profile": "av-dub",
                "dub_text": "original",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        dub_params = {
            stage["type"]: stage["params"]
            for stage in body["stages"]
            if stage["type"] in ("diarize", "tts_synthesize", "align_duration")
        }
        assert all(p.get("dub_text") == "original" for p in dub_params.values())

        url = f"/tasks/default/{body['id']}"
        cleared = client.patch(url, json={"dub_text": "auto"}, headers=headers)
        assert cleared.status_code == 200, cleared.text
        assert all(
            "dub_text" not in stage["params"] for stage in cleared.json()["stages"]
        )

        assert client.patch(
            url, json={"dub_text": "gibberish"}, headers=headers
        ).status_code == 422


def write_task_artifact(client, project: str, task_id: str, index: int, name: str, payload) -> None:
    from traduko.artifacts import ArtifactStore

    store = client.app.state.workspace.store
    ArtifactStore(store.task_dir(project, task_id)).write_json(index, name, payload)


TIMESTAMPED_ASR = {
    "language": "en",
    "duration": 4.0,
    "timestamps": True,
    "segments": [{"id": 1, "start": 0.0, "end": 2.0, "text": "hello"}],
}


def test_patch_switches_dub_on_appends_audio_dub_group(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="audio-transcribe")
        write_task_artifact(client, "default", task_id, 2, "asr.json", TIMESTAMPED_ASR)

        response = client.patch(
            f"/tasks/default/{task_id}/switches", json={"dub": True}, headers=headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert [stage["type"] for stage in body["stages"]] == [
            "extract_audio",
            "asr",
            "export_transcript",
            "diarize",
            "tts_synthesize",
            "align_duration",
            "mix_audio",
            "export_audio",
        ]
        appended = body["stages"][3:]
        assert all(stage["status"] == "pending" for stage in appended)
        assert body["switches"]["dub"] is True


def test_patch_switches_dub_on_appends_video_dub_group(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="av-default")
        write_task_artifact(client, "default", task_id, 2, "asr.json", TIMESTAMPED_ASR)

        response = client.patch(
            f"/tasks/default/{task_id}/switches", json={"dub": True}, headers=headers
        )

        assert response.status_code == 200, response.text
        types = [stage["type"] for stage in response.json()["stages"]]
        assert types[-5:] == [
            "diarize",
            "tts_synthesize",
            "align_duration",
            "mix_audio",
            "mux",
        ]


def test_patch_switches_dub_requires_timestamped_transcript(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="audio-transcribe")
        write_task_artifact(
            client,
            "default",
            task_id,
            2,
            "asr.json",
            {**TIMESTAMPED_ASR, "timestamps": False},
        )

        response = client.patch(
            f"/tasks/default/{task_id}/switches", json={"dub": True}, headers=headers
        )

        assert response.status_code == 409
        assert "timestamp" in response.json()["detail"]


def test_patch_switches_dub_append_on_completed_task_goes_pending(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="audio-transcribe")
        mark_task_completed(client, "default", task_id)
        write_task_artifact(client, "default", task_id, 2, "asr.json", TIMESTAMPED_ASR)

        response = client.patch(
            f"/tasks/default/{task_id}/switches", json={"dub": True}, headers=headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "pending"
        assert body["stages"][0]["status"] == "completed"


def set_config(client, headers, **sections) -> None:
    body = client.get("/config", headers=headers).json()
    for section, values in sections.items():
        body.setdefault(section, {}).update(values)
    assert client.put("/config", json=body, headers=headers).status_code == 200


def test_create_audio_task_applies_global_pipeline_defaults(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        # Default audio.dub_enabled=False: an audio task created with a dub
        # profile starts with its dub group skipped.
        task_id = create_task(client, headers, tmp_path, profile="audio-dub")
        body = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        by_type = {stage["type"]: stage for stage in body["stages"]}
        assert body["switches"]["dub"] is False
        assert body["switches"]["translate"] is True
        assert by_type["tts_synthesize"]["status"] == "skipped"
        assert by_type["export_audio"]["status"] == "skipped"
        assert by_type["translate"]["status"] == "pending"


def test_create_audio_task_translate_disabled_skips_translate_group(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        set_config(client, headers, audio={"translate_enabled": False})
        task_id = create_task(client, headers, tmp_path, profile="audio-translate")
        body = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        by_type = {stage["type"]: stage for stage in body["stages"]}
        assert body["switches"]["translate"] is False
        assert by_type["translate"]["status"] == "skipped"
        assert by_type["proofread"]["status"] == "skipped"
        assert by_type["export_subtitles"]["status"] == "skipped"
        assert by_type["export_transcript"]["status"] == "pending"


def test_create_video_task_diarize_default_applies(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        set_config(client, headers, dubbing={"diarize_enabled": False})
        task_id = create_task(client, headers, tmp_path, profile="av-dub")
        body = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        by_type = {stage["type"]: stage for stage in body["stages"]}
        assert body["switches"]["diarize"] is False
        assert by_type["diarize"]["status"] == "skipped"
        assert by_type["tts_synthesize"]["status"] == "pending"


def test_create_task_without_switchable_stages_leaves_switches_none(
    tmp_path: Path,
) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = create_task(client, headers, tmp_path, profile="subtitle-translate")
        body = client.get(f"/tasks/default/{task_id}", headers=headers).json()
        assert body["switches"] is None


def test_dub_engines_endpoint_lists_catalog(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        resp = client.get("/dub/engines", headers=headers)
        assert resp.status_code == 200
        engines = resp.json()["engines"]
        by_id = {e["id"]: e for e in engines}
        assert set(by_id) == {"voxcpm2", "say_preview", "cloud_placeholder"}
        assert by_id["voxcpm2"]["kind"] == "local"
        assert by_id["cloud_placeholder"]["kind"] == "placeholder"
        assert by_id["cloud_placeholder"]["available"] is False


def _dub_task(client, headers, tmp_path, profile="with-dub"):
    create_profile(
        tmp_path,
        "with-dub",
        ["diarize", "tts_synthesize", "align_duration", "mix_audio"],
    )
    resp = client.post(
        "/tasks",
        json={"input_path": str(make_input(tmp_path)), "profile": "with-dub"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_get_dub_params_aggregates_stage_params(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _dub_task(client, headers, tmp_path)
        # Seed params via the existing voice_mode patch path.
        client.patch(
            f"/tasks/default/{task_id}",
            json={"voice_mode": "design", "voice_instruction": "沉穩男聲"},
            headers=headers,
        )
        resp = client.get(f"/tasks/default/{task_id}/dub/params", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["engine_id"] is None
        assert body["voice_mode"] == "design"
        assert body["instruction"] == "沉穩男聲"
        assert body["dub_text"] in (None, "auto")


def test_patch_dub_params_writes_engine_and_voice(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _dub_task(client, headers, tmp_path)
        resp = client.patch(
            f"/tasks/default/{task_id}/dub/params",
            json={"engine_id": "voxcpm2", "voice_mode": "preview",
                  "preview_voice": "Mei-Jia", "preview_rate": 180},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        # GET reflects the write.
        got = client.get(f"/tasks/default/{task_id}/dub/params", headers=headers).json()
        assert got["engine_id"] == "voxcpm2"
        assert got["voice_mode"] == "preview"
        assert got["preview_voice"] == "Mei-Jia"
        assert got["preview_rate"] == 180


def test_patch_dub_params_rejects_placeholder_engine(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _dub_task(client, headers, tmp_path)
        resp = client.patch(
            f"/tasks/default/{task_id}/dub/params",
            json={"engine_id": "cloud_placeholder"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "cloud_placeholder" in resp.json()["detail"]


def test_dub_params_404_without_dub_group(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "sub", ["ingest_subtitle", "translate"])
        resp = client.post(
            "/tasks",
            json={"input_path": str(make_input(tmp_path)), "profile": "sub"},
            headers=headers,
        )
        task_id = resp.json()["id"]
        get = client.get(f"/tasks/default/{task_id}/dub/params", headers=headers)
        assert get.status_code == 422


def test_redub_from_synthesize_resets_tts_onward(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _dub_task(client, headers, tmp_path)
        # Mark dub stages completed to simulate prior run.
        ws = client.app.state.workspace
        rec = ws.store.load("default", task_id)
        for st in rec.stages:
            from traduko.models import StageStatus
            st.status = StageStatus.COMPLETED
        ws.store.save(rec)
        resp = client.post(
            f"/tasks/default/{task_id}/dub/redub",
            json={"from": "synthesize"},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text
        rec = ws.store.load("default", task_id)
        by_type = {s.type: s.status for s in rec.stages}
        assert by_type["diarize"] == "completed"
        assert by_type["tts_synthesize"] == "pending"
        assert by_type["align_duration"] == "pending"
        assert by_type["mix_audio"] == "pending"


def test_redub_from_diarize_resets_diarize_onward(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _dub_task(client, headers, tmp_path)
        ws = client.app.state.workspace
        rec = ws.store.load("default", task_id)
        for st in rec.stages:
            from traduko.models import StageStatus
            st.status = StageStatus.COMPLETED
        ws.store.save(rec)
        resp = client.post(
            f"/tasks/default/{task_id}/dub/redub",
            json={"from": "diarize"},
            headers=headers,
        )
        assert resp.status_code == 202
        rec = ws.store.load("default", task_id)
        by_type = {s.type: s.status for s in rec.stages}
        assert by_type["diarize"] == "pending"
        assert by_type["tts_synthesize"] == "pending"
        assert by_type["mix_audio"] == "pending"


def test_redub_running_409(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _dub_task(client, headers, tmp_path)
        from traduko.executor import CancelToken
        client.app.state.worker._cancels[("default", task_id)] = CancelToken()
        resp = client.post(
            f"/tasks/default/{task_id}/dub/redub",
            json={"from": "synthesize"},
            headers=headers,
        )
        assert resp.status_code == 409


def test_redub_without_dub_group_422(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        create_profile(tmp_path, "sub", ["ingest_subtitle", "translate"])
        resp = client.post(
            "/tasks",
            json={"input_path": str(make_input(tmp_path)), "profile": "sub"},
            headers=headers,
        )
        task_id = resp.json()["id"]
        resp = client.post(
            f"/tasks/default/{task_id}/dub/redub",
            json={"from": "synthesize"},
            headers=headers,
        )
        assert resp.status_code == 422


# --- Export studio -------------------------------------------------------


def _export_task(client, headers, tmp_path: Path) -> str:
    create_profile(tmp_path, "with-export", ["ingest_subtitle", "translate"])
    resp = client.post(
        "/tasks",
        json={"input_path": str(make_input(tmp_path)), "profile": "with-export"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_post_export_appends_stage_and_enqueues(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        client.app.state.worker.enqueue = lambda project, task_id: True
        resp = client.post(
            f"/tasks/default/{task_id}/exports",
            json={"kind": "video", "params": {"container": "mp4", "crf": 22}},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text
        assert resp.json()["queued"] is True
        rec = client.app.state.workspace.store.load("default", task_id)
        last = rec.stages[-1]
        assert last.type == "export_video"
        assert last.status == "pending"
        assert last.params["crf"] == 22
        assert last.params["container"] == "mp4"


def test_post_export_audio_kind_appends_audio_stage(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        client.app.state.worker.enqueue = lambda project, task_id: True
        resp = client.post(
            f"/tasks/default/{task_id}/exports",
            json={"kind": "audio", "params": {"format": "mp3", "bitrate_kbps": 160}},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text
        rec = client.app.state.workspace.store.load("default", task_id)
        assert rec.stages[-1].type == "export_audio_custom"
        assert rec.stages[-1].params["format"] == "mp3"


def test_post_export_on_completed_task_returns_it_to_pending(tmp_path: Path) -> None:
    from traduko.models import StageStatus, TaskStatus

    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        ws = client.app.state.workspace
        rec = ws.store.load("default", task_id)
        rec.status = TaskStatus.COMPLETED
        for stage in rec.stages:
            stage.status = StageStatus.COMPLETED
        ws.store.save(rec)
        # Hold the queue so the assertions see the appended state rather than
        # whatever the worker has already done to it.
        client.app.state.worker.enqueue = lambda project, task_id: True
        resp = client.post(
            f"/tasks/default/{task_id}/exports",
            json={"kind": "video", "params": {}},
            headers=headers,
        )
        assert resp.status_code == 202, resp.text
        rec = ws.store.load("default", task_id)
        assert rec.status == "pending"
        assert rec.stages[-1].status == "pending"


def test_post_export_while_running_409(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        from traduko.executor import CancelToken
        client.app.state.worker._cancels[("default", task_id)] = CancelToken()
        resp = client.post(
            f"/tasks/default/{task_id}/exports",
            json={"kind": "video", "params": {}},
            headers=headers,
        )
        assert resp.status_code == 409


def test_post_export_with_missing_input_422(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        (tmp_path / "in.srt").unlink()
        resp = client.post(
            f"/tasks/default/{task_id}/exports",
            json={"kind": "video", "params": {}},
            headers=headers,
        )
        assert resp.status_code == 422


def test_post_export_rejects_unknown_kind(tmp_path: Path) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        resp = client.post(
            f"/tasks/default/{task_id}/exports",
            json={"kind": "comic", "params": {}},
            headers=headers,
        )
        assert resp.status_code == 422


def test_export_estimate_reports_size_eta_and_disk(tmp_path: Path, monkeypatch) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        monkeypatch.setattr(
            "traduko.service.app.probe_media",
            lambda path: {
                "duration": 120.0,
                "bit_rate": 2_000_000,
                "width": 1920,
                "height": 1080,
                "video_codec": "h264",
                "audio_streams": [],
            },
        )
        resp = client.get(
            f"/tasks/default/{task_id}/exports/estimate",
            params={"kind": "video", "crf": 20, "audio_bitrate_kbps": 192},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["size_bytes"] > 0
        assert body["eta_seconds"] > 0
        assert body["disk_ok"] is True
        assert body["disk_available"] > 0
        assert body["duration"] == 120.0


def test_export_estimate_flags_insufficient_disk(tmp_path: Path, monkeypatch) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        monkeypatch.setattr(
            "traduko.service.app.probe_media",
            lambda path: {
                "duration": 120.0,
                "bit_rate": 2_000_000,
                "width": 1920,
                "height": 1080,
                "video_codec": "h264",
                "audio_streams": [],
            },
        )
        monkeypatch.setattr(
            "traduko.service.app.check_disk_space", lambda d, need: (False, 1024)
        )
        resp = client.get(
            f"/tasks/default/{task_id}/exports/estimate",
            params={"kind": "video"},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["disk_ok"] is False


def test_export_estimate_probe_failure_422(tmp_path: Path, monkeypatch) -> None:
    from traduko.media import MediaError

    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)

        def boom(path):
            raise MediaError("ffprobe failed")

        monkeypatch.setattr("traduko.service.app.probe_media", boom)
        resp = client.get(
            f"/tasks/default/{task_id}/exports/estimate",
            params={"kind": "video"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "ffprobe" in resp.json()["detail"]


def test_export_estimate_audio_kind_uses_bitrate(tmp_path: Path, monkeypatch) -> None:
    with service(tmp_path) as (client, headers, token):
        task_id = _export_task(client, headers, tmp_path)
        monkeypatch.setattr(
            "traduko.service.app.probe_media",
            lambda path: {
                "duration": 100.0,
                "bit_rate": None,
                "width": None,
                "height": None,
                "video_codec": None,
                "audio_streams": [],
            },
        )
        resp = client.get(
            f"/tasks/default/{task_id}/exports/estimate",
            params={"kind": "audio", "format": "m4a", "bitrate_kbps": 192},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["size_bytes"] == pytest.approx(
            192 * 1000 * 100 / 8, rel=0.01
        )
