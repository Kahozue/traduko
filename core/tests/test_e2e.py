import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from traduko.service.app import create_app

from traduko.asr import AsrResult, AsrSegment, register_asr
from traduko.cli import app
from traduko.config import CoreConfig, NotificationsConfig, save_config
from traduko.media import ffmpeg_available

runner = CliRunner()

SRT_INPUT = """1
00:00:01,000 --> 00:00:02,000
hello

2
00:00:03,000 --> 00:00:04,000
world
"""


def test_subtitle_pipeline_end_to_end(tmp_path: Path) -> None:
    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    src = tmp_path / "in.srt"
    src.write_text(SRT_INPUT, encoding="utf-8")

    created = runner.invoke(
        app, ["task", "create", str(src), "--profile", "subtitle-translate"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output
    assert "[stage_progress]" in ran.output

    artifacts = tmp_path / "projects" / "default" / "tasks" / task_id / "artifacts"
    translation = json.loads(
        (artifacts / "02-translation.json").read_text(encoding="utf-8")
    )
    assert translation["schema_version"] == 1
    assert [s["target"] for s in translation["segments"]] == ["[T] hello", "[T] world"]
    report = json.loads(
        (artifacts / "03-proofread-report.json").read_text(encoding="utf-8")
    )
    assert report["converged"] is True
    srt_out = (artifacts / "04-subtitles.srt").read_text(encoding="utf-8")
    assert "[T] hello" in srt_out and "-->" in srt_out


@register_asr("e2e-fake-asr")
class E2eFakeAsr:
    def __init__(self, **_params) -> None:
        pass

    def transcribe(self, audio_path, *, language=None, on_progress=None):
        assert Path(audio_path).exists()
        return AsrResult(
            language="en",
            duration=2.0,
            segments=[AsrSegment(start=0.2, end=1.8, text="hello world.")],
        )


AV_PROFILE = """schema_version: 1
name: av-fake
stages:
  - type: extract_audio
  - type: asr
    params:
      provider: e2e-fake-asr
  - type: segment
  - type: translate
    params:
      provider: fake
      target_language: en
  - type: export_subtitles
    params:
      formats: [srt, ass]
  - type: hardburn
"""


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
def test_av_pipeline_with_hardburn(tmp_path: Path) -> None:
    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    (tmp_path / "profiles").mkdir(parents=True)
    (tmp_path / "profiles" / "av-fake.yaml").write_text(AV_PROFILE, encoding="utf-8")
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-f", "lavfi", "-i", "color=c=black:s=128x72:d=2",
            "-shortest", str(clip),
        ],
        check=True, capture_output=True,
    )

    created = runner.invoke(
        app, ["task", "create", str(clip), "--profile", "av-fake"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output

    artifacts = tmp_path / "projects" / "default" / "tasks" / task_id / "artifacts"
    assert (artifacts / "01-audio.wav").stat().st_size > 0
    asr = json.loads((artifacts / "02-asr.json").read_text(encoding="utf-8"))
    assert asr["language"] == "en"
    translation = json.loads(
        (artifacts / "04-translation.json").read_text(encoding="utf-8")
    )
    assert translation["segments"][0]["target"].startswith("[T] ")
    assert (artifacts / "05-subtitles.srt").exists()
    assert (artifacts / "05-subtitles.ass").exists()
    assert (artifacts / "06-video.mp4").stat().st_size > 0


PROOFREAD_SCRIPT = [
    '{"tool": "read_segments", "arguments": {"start_id": 1, "end_id": 2, "context": 0}}',
    '{"tool": "check_glossary", "arguments": {}}',
    '{"tool": "edit_segment", "arguments": {"id": 2, "new_target": "Mondo!", "reason": "punchier"}}',
    '{"tool": "end_round", "arguments": {"summary": "fixed one"}}',
    '{"tool": "read_segments", "arguments": {"start_id": 1, "end_id": 2, "context": 0}}',
    '{"done": true, "summary": "no remaining issues"}',
]

PROOFREAD_PROFILE = """schema_version: 1
name: sub-proofread
stages:
  - type: ingest_subtitle
  - type: translate
    params:
      provider: fake
      target_language: eo
  - type: proofread
    params:
      provider: agent
      model: test-model
      intensity: deep
      max_rounds: 2
  - type: export_subtitles
    params:
      formats: [srt]
"""


def test_subtitle_pipeline_with_agent_proofread(tmp_path: Path) -> None:
    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    src = tmp_path / "in.srt"
    src.write_text(SRT_INPUT, encoding="utf-8")
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={"agent": {"type": "scripted", "responses": PROOFREAD_SCRIPT}}
        ),
    )
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profiles" / "sub-proofread.yaml").write_text(
        PROOFREAD_PROFILE, encoding="utf-8"
    )

    created = runner.invoke(
        app, ["task", "create", str(src), "--profile", "sub-proofread"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output

    task_dir = tmp_path / "projects" / "default" / "tasks" / task_id
    artifacts = task_dir / "artifacts"

    translation = json.loads(
        (artifacts / "03-translation.json").read_text(encoding="utf-8")
    )
    assert translation["segments"][0]["target"] == "[T] hello"
    assert translation["segments"][1]["target"] == "Mondo!"

    report = json.loads(
        (artifacts / "03-proofread-report.json").read_text(encoding="utf-8")
    )
    assert report["converged"] is True and report["rounds"] == 2
    assert len(report["edits"]) == 1

    srt_out = (artifacts / "04-subtitles.srt").read_text(encoding="utf-8")
    assert "Mondo!" in srt_out and "[T] hello" in srt_out

    runs = list((task_dir / "agent-runs").glob("03-proofread-*.jsonl"))
    assert len(runs) == 1 and runs[0].stat().st_size > 0


def test_pipeline_notifies_webhook_and_logs_events(tmp_path: Path) -> None:
    received: list[dict] = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Hook)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
        src = tmp_path / "in.srt"
        src.write_text(SRT_INPUT, encoding="utf-8")
        save_config(
            tmp_path,
            CoreConfig(
                notifications=NotificationsConfig(
                    channels=[
                        {
                            "type": "webhook",
                            "url": f"http://127.0.0.1:{port}/hook",
                            "events": ["task_completed"],
                        }
                    ]
                )
            ),
        )

        created = runner.invoke(
            app,
            ["task", "create", str(src), "--profile", "subtitle-translate"],
            env=env,
        )
        assert created.exit_code == 0, created.output
        task_id = created.output.strip().splitlines()[-1]

        ran = runner.invoke(app, ["task", "run", task_id], env=env)
        assert ran.exit_code == 0, ran.output
        assert "completed" in ran.output
    finally:
        server.shutdown()
        thread.join()

    assert [p["type"] for p in received] == ["task_completed"]
    assert received[0]["task_id"] == task_id

    log_path = (
        tmp_path / "projects" / "default" / "tasks" / task_id
        / "logs" / "events.jsonl"
    )
    lines = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").strip().splitlines()
    ]
    types = [line["type"] for line in lines]
    assert types[0] == "task_started"
    assert types[-1] == "task_completed"
    assert "stage_progress" in types


def test_service_api_full_pipeline_with_ws_events(tmp_path: Path) -> None:
    received: list[dict] = []

    class Hook(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Hook)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        save_config(
            tmp_path,
            CoreConfig(
                notifications=NotificationsConfig(
                    channels=[
                        {
                            "type": "webhook",
                            "url": f"http://127.0.0.1:{port}/hook",
                            "events": ["task_completed"],
                        }
                    ]
                )
            ),
        )
        src = tmp_path / "in.srt"
        src.write_text(SRT_INPUT, encoding="utf-8")

        app_instance = create_app(tmp_path)
        token = (
            (tmp_path / "config" / "api-token").read_text(encoding="utf-8").strip()
        )
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app_instance) as client:
            created = client.post(
                "/tasks",
                json={"input_path": str(src), "profile": "subtitle-translate"},
                headers=headers,
            )
            assert created.status_code == 201, created.text
            task_id = created.json()["id"]

            with client.websocket_connect(f"/ws/events?token={token}") as stream:
                ran = client.post(f"/tasks/default/{task_id}/run", headers=headers)
                assert ran.status_code == 202, ran.text

                deadline = time.monotonic() + 10
                shown = client.get(f"/tasks/default/{task_id}", headers=headers).json()
                while time.monotonic() < deadline:
                    shown = client.get(
                        f"/tasks/default/{task_id}", headers=headers
                    ).json()
                    if shown["status"] == "completed":
                        break
                    time.sleep(0.01)
                assert shown["status"] == "completed"

                types: list[str] = []
                while "task_completed" not in types:
                    types.append(stream.receive_json()["type"])
    finally:
        server.shutdown()
        thread.join()

    assert types[0] == "task_started"
    assert "stage_progress" in types

    assert [p["type"] for p in received] == ["task_completed"]
    assert received[0]["task_id"] == task_id

    artifacts = tmp_path / "projects" / "default" / "tasks" / task_id / "artifacts"
    assert (artifacts / "04-subtitles.srt").exists()


MD_NOVEL = "# Chapter\n\nHello paragraph.\n\nSecond paragraph.\n"


def test_novel_pipeline_end_to_end_with_fake_translation(tmp_path: Path) -> None:
    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    src = tmp_path / "novel.md"
    src.write_text(MD_NOVEL, encoding="utf-8")

    created = runner.invoke(
        app, ["task", "create", str(src), "--profile", "novel-translate"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output

    artifacts = tmp_path / "projects" / "default" / "tasks" / task_id / "artifacts"
    document = json.loads((artifacts / "01-document.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    chunks = json.loads((artifacts / "02-chunks.json").read_text(encoding="utf-8"))
    assert len(chunks["chunks"]) >= 1
    translation = json.loads(
        (artifacts / "03-translation.json").read_text(encoding="utf-8")
    )
    assert all(c["status"] == "translated" for c in translation["chunks"])
    qc_first = json.loads((artifacts / "04-qc.json").read_text(encoding="utf-8"))
    assert qc_first["flags"] == []
    # Second translate pass is a no-op when qc is clean.
    assert not (artifacts / "05-translation.json").exists()
    qc_final = json.loads((artifacts / "06-qc.json").read_text(encoding="utf-8"))
    assert qc_final["flags"] == []
    out = (artifacts / "07-translated.md").read_text(encoding="utf-8")
    assert out == "[T] # Chapter\n\n[T] Hello paragraph.\n\n[T] Second paragraph.\n"


def test_novel_pipeline_requeues_flagged_chunks(tmp_path: Path) -> None:
    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    src = tmp_path / "novel.md"
    src.write_text(MD_NOVEL, encoding="utf-8")
    echo_round = json.dumps(
        [
            {"id": "b-00001", "text": "# Chapter\n"},
            {"id": "b-00003", "text": "Hello paragraph.\n"},
            {"id": "b-00005", "text": "Second paragraph.\n"},
        ]
    )
    good_round = json.dumps(
        [
            {"id": "b-00001", "text": "# Ĉapitro\n"},
            {"id": "b-00003", "text": "Saluton alineo.\n"},
            {"id": "b-00005", "text": "Dua alineo.\n"},
        ]
    )
    # Each stage builds its own provider instance, so script the two
    # translate passes through separate provider entries.
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={
                "novel-first": {"type": "scripted", "responses": [echo_round]},
                "novel-retry": {"type": "scripted", "responses": [good_round]},
            }
        ),
    )
    (tmp_path / "profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "profiles" / "novel-scripted.yaml").write_text(
        """schema_version: 1
name: novel-scripted
stages:
  - type: ingest_document
  - type: chunk
  - type: translate_chunks
    params:
      provider: novel-first
      target_language: eo
  - type: qc_scan
    params:
      target_language: eo
  - type: translate_chunks
    params:
      provider: novel-retry
      target_language: eo
      only_flagged: true
  - type: qc_scan
    params:
      target_language: eo
  - type: export_document
""",
        encoding="utf-8",
    )

    created = runner.invoke(
        app, ["task", "create", str(src), "--profile", "novel-scripted"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output

    artifacts = tmp_path / "projects" / "default" / "tasks" / task_id / "artifacts"
    qc_first = json.loads((artifacts / "04-qc.json").read_text(encoding="utf-8"))
    assert [f["type"] for f in qc_first["flags"]] == ["echo"]
    retry = json.loads((artifacts / "05-translation.json").read_text(encoding="utf-8"))
    assert retry["chunks"][0]["blocks"][0]["text"] == "# Ĉapitro\n"
    qc_final = json.loads((artifacts / "06-qc.json").read_text(encoding="utf-8"))
    assert qc_final["flags"] == []
    out = (artifacts / "07-translated.md").read_text(encoding="utf-8")
    assert out == "# Ĉapitro\n\nSaluton alineo.\n\nDua alineo.\n"


def test_novel_pipeline_epub_end_to_end(tmp_path: Path) -> None:
    from test_documents_epub import make_epub
    from traduko.documents.epubdoc import parse_epub

    env = {"TRADUKO_DATA_ROOT": str(tmp_path)}
    src = tmp_path / "novel.epub"
    make_epub(src)

    created = runner.invoke(
        app, ["task", "create", str(src), "--profile", "novel-translate"], env=env
    )
    assert created.exit_code == 0, created.output
    task_id = created.output.strip().splitlines()[-1]

    ran = runner.invoke(app, ["task", "run", task_id], env=env)
    assert ran.exit_code == 0, ran.output
    assert "completed" in ran.output

    artifacts = tmp_path / "projects" / "default" / "tasks" / task_id / "artifacts"
    out_doc = parse_epub(artifacts / "07-translated.epub")
    texts = [b.text for ch in out_doc.chapters for b in ch.blocks]
    assert "[T] First paragraph." in texts
    assert "First paragraph." not in texts
