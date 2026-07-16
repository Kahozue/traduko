"""Render a single subtitle frame to PNG via ffmpeg+libass.

The style editor's "exact frame" preview and the final hardburn share the
same libass rendering path, so what you preview is what you get.
"""
from __future__ import annotations

from pathlib import Path

from .media import _escape_filter_path
from .media import run as run_media
from .styles import SubtitleStyle, serialize_ass
from .subtitles import Cue


def build_frame_cmd(
    ass_path: Path, out_png: Path, width: int, height: int, background: str
) -> list[str]:
    vf = f"ass={_escape_filter_path(ass_path)}"
    return [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={background}:s={width}x{height}:d=1",
        "-vf", vf,
        "-frames:v", "1",
        str(out_png),
    ]


def render_style_frame(
    style: SubtitleStyle,
    text: str,
    out_png: Path,
    *,
    width: int = 1280,
    height: int = 720,
    background: str = "black",
    work_dir: Path,
) -> Path:
    cue = Cue(id=1, start=0.0, end=2.0, text=text)
    ass_body = serialize_ass([cue], style)
    ass_path = work_dir / "preview.ass"
    ass_path.write_text(ass_body, encoding="utf-8")
    run_media(build_frame_cmd(ass_path, out_png, width, height, background))
    return out_png
