import shutil
import subprocess
from pathlib import Path

import pytest

from traduko.media import (
    MediaError,
    build_extract_audio_cmd,
    build_hardburn_cmd,
    ffmpeg_available,
    probe_duration,
    run,
)

HAS_FFMPEG = ffmpeg_available()


def test_extract_audio_cmd(tmp_path: Path) -> None:
    cmd = build_extract_audio_cmd(tmp_path / "in.mp4", tmp_path / "01-audio.wav")
    assert cmd[0] == "ffmpeg"
    assert "-ac" in cmd and cmd[cmd.index("-ac") + 1] == "1"
    assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "16000"
    assert cmd[-1].endswith("01-audio.wav")


def test_hardburn_cmd_escapes_filter_path(tmp_path: Path) -> None:
    ass = tmp_path / "sub's.ass"
    cmd = build_hardburn_cmd(tmp_path / "in.mp4", ass, tmp_path / "out.mp4")
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("ass=")
    assert "'" not in vf.replace("\\'", "")


def test_hardburn_cmd_with_fonts_dir(tmp_path: Path) -> None:
    cmd = build_hardburn_cmd(
        tmp_path / "in.mp4", tmp_path / "s.ass", tmp_path / "out.mp4",
        fonts_dir=tmp_path / "fonts",
    )
    assert "fontsdir=" in cmd[cmd.index("-vf") + 1]


def test_run_raises_media_error_on_failure() -> None:
    with pytest.raises(MediaError):
        run(["ffmpeg-definitely-not-installed", "-version"])


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_extract_and_probe_integration(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
            "-shortest", str(clip),
        ],
        check=True, capture_output=True,
    )
    wav = tmp_path / "01-audio.wav"
    run(build_extract_audio_cmd(clip, wav))
    assert wav.exists() and wav.stat().st_size > 0
    assert probe_duration(clip) == pytest.approx(1.0, abs=0.3)
