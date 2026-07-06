"""Thin ffmpeg/ffprobe wrappers. All media I/O funnels through here."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class MediaError(Exception):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def build_extract_audio_cmd(input_path: Path, output_path: Path) -> list[str]:
    return [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
        str(output_path),
    ]


def _escape_filter_path(path: Path) -> str:
    # ffmpeg filter args treat \ : ' specially.
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build_hardburn_cmd(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
    fonts_dir: Path | None = None,
) -> list[str]:
    vf = f"ass={_escape_filter_path(ass_path)}"
    if fonts_dir is not None:
        vf += f":fontsdir={_escape_filter_path(fonts_dir)}"
    return [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vf", vf, "-c:a", "copy",
        str(output_path),
    ]


def run(cmd: list[str]) -> None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise MediaError(f"executable not found: {cmd[0]}") from error
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        raise MediaError(f"{cmd[0]} failed ({result.returncode}): " + " | ".join(tail))


def probe_duration(input_path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", str(input_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed for {input_path}")
    data = json.loads(result.stdout)
    try:
        return float(data["format"]["duration"])
    except (KeyError, ValueError) as error:
        raise MediaError(f"no duration in probe output for {input_path}") from error
