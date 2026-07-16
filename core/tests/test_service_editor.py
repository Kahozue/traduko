import json
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from traduko.media import ffmpeg_available

from traduko.artifacts import ArtifactStore
from traduko.models import StageStatus, TaskRecord
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


def _mark_pipeline_completed(tmp_path, task):
    """Simulate a finished run: all stages completed, translate produced 05-translation.json."""
    task_dir = tmp_path / "projects" / task["project"] / "tasks" / task["id"]
    record = TaskRecord.model_validate_json((task_dir / "task.json").read_text())
    for st in record.stages:
        st.status = StageStatus.COMPLETED
        if st.type == "translate":
            st.artifacts = ["05-translation.json"]
    record.status = "completed"
    (task_dir / "task.json").write_text(record.model_dump_json(indent=2))


def test_save_translation_writes_new_version_and_resets_downstream(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        _mark_pipeline_completed(tmp_path, task)

        edited = {
            "source_language": "en", "target_language": "zh",
            "segments": [{"id": 1, "start": 0.0, "end": 1.0, "source": "hi", "target": "改過"}],
        }
        resp = client.put(
            f"/tasks/{task['project']}/{task['id']}/artifacts/translation.json",
            headers=headers, json=edited,
        )
        assert resp.status_code == 200
        assert resp.json()["file"] == "06-translation.json"
        assert resp.json()["stages_reset"] >= 1
        # latest version reads back the edit
        latest = client.get(
            f"/tasks/{task['project']}/{task['id']}/artifacts/translation.json",
            headers=headers,
        ).json()
        assert latest["segments"][0]["target"] == "改過"


def test_save_translation_reopens_completed_task(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        _mark_pipeline_completed(tmp_path, task)

        edited = {
            "source_language": "en", "target_language": "zh",
            "segments": [{"id": 1, "start": 0.0, "end": 1.0, "source": "hi", "target": "改過"}],
        }
        client.put(
            f"/tasks/{task['project']}/{task['id']}/artifacts/translation.json",
            headers=headers, json=edited,
        )
        shown = client.get(f"/tasks/{task['project']}/{task['id']}", headers=headers).json()
        assert shown["status"] == "pending"


def test_save_invalid_translation_returns_422(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        resp = client.put(
            f"/tasks/{task['project']}/{task['id']}/artifacts/translation.json",
            headers=headers, json={"segments": [{"id": 1, "source": "hi"}]},
        )
        assert resp.status_code == 422


def test_get_styles_returns_default_preset(tmp_path):
    with service(tmp_path) as (client, headers):
        resp = client.get("/styles", headers=headers)
        assert resp.status_code == 200
        assert "default" in resp.json()


def test_put_styles_persists(tmp_path):
    with service(tmp_path) as (client, headers):
        preset = {"default": {"font_name": "Arial", "font_size": 60,
                              "primary_color": "#FFFFFF", "outline_color": "#000000",
                              "outline": 2.0, "shadow": 0.0, "bold": False,
                              "alignment": 2, "margin_v": 40}}
        resp = client.put("/styles", headers=headers, json=preset)
        assert resp.status_code == 200
        saved = yaml.safe_load((tmp_path / "config" / "styles.yaml").read_text())
        assert saved["default"]["font_size"] == 60


def test_render_frame_without_ffmpeg_returns_503(tmp_path, monkeypatch):
    monkeypatch.setattr("traduko.service.app.ffmpeg_available", lambda: False)
    with service(tmp_path) as (client, headers):
        (tmp_path / "in.srt").write_text(SRT, encoding="utf-8")
        task = client.post(
            "/tasks", headers=headers,
            json={"input_path": str(tmp_path / "in.srt"), "profile": "subtitle-translate"},
        ).json()
        resp = client.post(
            f"/tasks/{task['project']}/{task['id']}/render-frame",
            headers=headers,
            json={"style": {"font_size": 48}, "text": "hi"},
        )
        assert resp.status_code == 503


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
def test_render_frame_returns_png(tmp_path):
    with service(tmp_path) as (client, headers):
        (tmp_path / "in.srt").write_text(SRT, encoding="utf-8")
        task = client.post(
            "/tasks", headers=headers,
            json={"input_path": str(tmp_path / "in.srt"), "profile": "subtitle-translate"},
        ).json()
        resp = client.post(
            f"/tasks/{task['project']}/{task['id']}/render-frame",
            headers=headers,
            json={"style": {"font_size": 48, "primary_color": "#FFEE00"}, "text": "Hi 世界"},
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_create_task_with_custom_name(tmp_path):
    with service(tmp_path) as (client, headers):
        (tmp_path / "in.srt").write_text(SRT, encoding="utf-8")
        resp = client.post(
            "/tasks", headers=headers,
            json={"input_path": str(tmp_path / "in.srt"),
                  "profile": "subtitle-translate", "name": "第三集"},
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "第三集"


def test_create_task_defaults_name_to_stem(tmp_path):
    with service(tmp_path) as (client, headers):
        (tmp_path / "movie.srt").write_text(SRT, encoding="utf-8")
        resp = client.post(
            "/tasks", headers=headers,
            json={"input_path": str(tmp_path / "movie.srt"),
                  "profile": "subtitle-translate"},
        )
        assert resp.json()["name"] == "movie"


def test_rename_task(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        resp = client.patch(
            f"/tasks/{task['project']}/{task['id']}",
            headers=headers, json={"name": "改名後"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "改名後"
        shown = client.get(
            f"/tasks/{task['project']}/{task['id']}", headers=headers
        ).json()
        assert shown["name"] == "改名後"
        rows = client.get("/tasks", headers=headers).json()
        assert rows[0]["name"] == "改名後"


def test_rename_task_rejects_blank(tmp_path):
    with service(tmp_path) as (client, headers):
        task = make_task_with_translation(client, headers, tmp_path)
        resp = client.patch(
            f"/tasks/{task['project']}/{task['id']}",
            headers=headers, json={"name": "   "},
        )
        assert resp.status_code == 422
