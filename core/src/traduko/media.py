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


def build_extract_mix_audio_cmd(input_path: Path, output_path: Path) -> list[str]:
    """Full-quality original audio for the dub mix (unlike the 16k mono
    ASR extraction)."""
    return [
        "ffmpeg", "-y", "-i", str(input_path),
        "-vn", "-ac", "2", "-ar", "48000", "-f", "wav",
        str(output_path),
    ]


def build_extract_clip_cmd(
    input_path: Path, start: float, duration: float, output_path: Path
) -> list[str]:
    return [
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "44100", "-f", "wav",
        str(output_path),
    ]


def build_atempo_cmd(input_path: Path, tempo: float, output_path: Path) -> list[str]:
    return [
        "ffmpeg", "-y", "-i", str(input_path),
        "-filter:a", f"atempo={tempo:.3f}",
        str(output_path),
    ]


def build_mix_filter_script(
    clip_offsets: list[float],
    duck_windows: list[tuple[float, float]],
    duck_volume: float,
) -> str:
    """filter_complex script mixing dub clips over the ducked original.
    Written to a file and passed via -filter_complex_script: with one
    between() term per subtitle segment the inline form outgrows ARG_MAX."""
    if duck_windows:
        enable = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in duck_windows)
        lines = [f"[0:a]volume={duck_volume}:enable='{enable}'[duck];\n"]
    else:
        lines = ["[0:a]anull[duck];\n"]
    labels = []
    for i, offset in enumerate(clip_offsets):
        ms = max(0, round(offset * 1000))
        lines.append(f"[{i + 1}:a]adelay={ms}|{ms}[d{i}];\n")
        labels.append(f"[d{i}]")
    lines.append(
        f"[duck]{''.join(labels)}amix=inputs={len(clip_offsets) + 1}"
        ":duration=first:normalize=0[out]\n"
    )
    return "".join(lines)


def build_mix_cmd(
    orig_audio: Path, clips: list[Path], script_path: Path, output_path: Path
) -> list[str]:
    cmd = ["ffmpeg", "-y", "-i", str(orig_audio)]
    for clip in clips:
        cmd += ["-i", str(clip)]
    cmd += [
        "-filter_complex_script", str(script_path),
        "-map", "[out]", "-ac", "2", "-ar", "48000",
        str(output_path),
    ]
    return cmd


def build_mux_cmd(video_path: Path, audio_path: Path, output_path: Path) -> list[str]:
    return [
        "ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
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
