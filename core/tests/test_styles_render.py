from pathlib import Path

import pytest

from traduko.media import ffmpeg_available
from traduko.styles import SubtitleStyle
from traduko.styles_render import build_frame_cmd, render_style_frame


def test_build_frame_cmd_uses_lavfi_color_and_ass_filter(tmp_path):
    ass = tmp_path / "s.ass"
    out = tmp_path / "f.png"
    cmd = build_frame_cmd(ass, out, 1280, 720, "black")
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "lavfi" in cmd
    assert "color=c=black:s=1280x720" in joined
    assert "ass=" in joined
    assert "-frames:v" in cmd
    assert str(out) == cmd[-1]


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
def test_render_style_frame_produces_png(tmp_path):
    out = render_style_frame(
        SubtitleStyle(font_size=48, primary_color="#FFEE00"),
        "Hello 世界",
        tmp_path / "frame.png",
        work_dir=tmp_path,
    )
    assert out.exists()
    assert out.stat().st_size > 0
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
