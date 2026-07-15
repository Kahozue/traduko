import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from traduko.asr import AsrResult, AsrSegment, register_asr
from traduko.cli import app
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
