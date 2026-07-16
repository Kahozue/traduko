import json
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from traduko.artifacts import ArtifactStore
from traduko.service.app import create_app


@contextmanager
def service(tmp_path: Path):
    app = create_app(tmp_path)
    token = (tmp_path / "config" / "api-token").read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        yield client, headers


SRT = "1\n00:00:00,000 --> 00:00:01,000\nhi\n"


def make_task_with_translation(client, headers, tmp_path):
    (tmp_path / "in.srt").write_text(SRT, encoding="utf-8")
    resp = client.post(
        "/tasks",
        headers=headers,
        json={"input_path": str(tmp_path / "in.srt"), "profile": "subtitle-translate"},
    )
    assert resp.status_code == 201
    task = resp.json()
    store = ArtifactStore(
        tmp_path / "projects" / task["project"] / "tasks" / task["id"]
    )
    store.write_json(
        5, "translation.json",
        {"source_language": "en", "target_language": "zh",
         "segments": [{"id": 1, "start": 0.0, "end": 1.0, "source": "hi", "target": "嗨"}]},
    )
    return task


def test_list_artifacts_returns_written_files(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        resp = client.get(
            f"/tasks/{task['project']}/{task['id']}/artifacts", headers=headers
        )
        assert resp.status_code == 200
        files = [item["file"] for item in resp.json()]
        assert "05-translation.json" in files


def test_read_latest_artifact(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        resp = client.get(
            f"/tasks/{task['project']}/{task['id']}/artifacts/translation.json",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["segments"][0]["target"] == "嗨"


def test_read_missing_artifact_returns_404(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        resp = client.get(
            f"/tasks/{task['project']}/{task['id']}/artifacts/nope.json",
            headers=headers,
        )
        assert resp.status_code == 404
