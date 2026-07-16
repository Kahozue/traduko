import json
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from traduko.service.app import create_app


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
