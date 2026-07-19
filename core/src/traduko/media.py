"""Thin ffmpeg/ffprobe wrappers. All media I/O funnels through here."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
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


VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv", ".m4v"}
)
AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aiff", ".wma"}
)


def media_kind_of(path: Path) -> str | None:
    """"video", "audio", or None for anything else (a compose task's input is
    the transcript file). Classification is by the file, not by the task's
    domain, and mirrors the app's lib/media.ts table."""
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    return None


def build_mix_cmd(
    orig_audio: Path | None,
    clips: list[Path],
    script_path: Path,
    output_path: Path,
    *,
    silence_duration: float | None = None,
) -> list[str]:
    """orig_audio None means there is no original track to mix over, so the
    bed is silence of silence_duration seconds. Giving it an explicit length
    keeps amix's duration=first meaning "as long as the dub timeline"."""
    if orig_audio is None:
        if silence_duration is None:
            raise MediaError("a silent mix bed needs a duration")
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-t", f"{silence_duration:.3f}",
            "-i", "anullsrc=r=48000:cl=stereo",
        ]
    else:
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


def build_silence_detect_cmd(input_path: Path) -> list[str]:
    """Silence scan for chunk-boundary planning; output goes to stderr."""
    return [
        "ffmpeg", "-i", str(input_path),
        "-af", "silencedetect=noise=-35dB:d=0.4",
        "-f", "null", "-",
    ]


def build_chunk_flac_cmd(
    input_path: Path, start: float, duration: float, output_path: Path
) -> list[str]:
    """One cloud-ASR chunk: 16 kHz mono FLAC keeps uploads far under the
    25 MB API limit without the lossy-transcode quality hit."""
    return [
        "ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
        "-i", str(input_path),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac",
        str(output_path),
    ]


def run_capture_stderr(cmd: list[str]) -> str:
    """Run a command whose useful output lands on stderr (silencedetect).
    A nonzero exit is still an error."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise MediaError(f"executable not found: {cmd[0]}") from error
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-5:]
        raise MediaError(f"{cmd[0]} failed ({result.returncode}): " + " | ".join(tail))
    return result.stderr or ""


def parse_silences(stderr: str) -> list[tuple[float, float]]:
    """(start, end) pairs from silencedetect stderr output; unmatched
    trailing starts are dropped."""
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in stderr.splitlines():
        if "silence_start:" in line:
            try:
                start = float(line.split("silence_start:")[1].split()[0])
            except (ValueError, IndexError):
                start = None
        elif "silence_end:" in line and start is not None:
            try:
                end = float(line.split("silence_end:")[1].split()[0])
            except (ValueError, IndexError):
                continue
            silences.append((start, end))
            start = None
    return silences


def plan_chunks(
    duration: float,
    silences: list[tuple[float, float]],
    *,
    target: float,
    hard_max: float,
) -> list[tuple[float, float]]:
    """Tile [0, duration] into chunks aiming at `target` seconds each,
    cutting at the silence midpoint nearest each target when one falls in
    the window [0.5*target, hard_max], else at hard_max. Pure function so
    boundary policy is unit-testable without ffmpeg."""
    if duration <= hard_max:
        return [(0.0, duration)]
    midpoints = [round((start + end) / 2, 3) for start, end in silences]
    chunks: list[tuple[float, float]] = []
    position = 0.0
    while duration - position > hard_max:
        window_lo = position + target * 0.5
        window_hi = position + hard_max
        candidates = [m for m in midpoints if window_lo <= m <= window_hi]
        if candidates:
            cut = min(candidates, key=lambda m: abs(m - (position + target)))
        else:
            cut = window_hi
        chunks.append((position, cut))
        position = cut
    chunks.append((position, duration))
    return chunks


def build_encode_audio_cmd(input_path: Path, output_path: Path, fmt: str) -> list[str]:
    """Final dubbed-audio encode. m4a for size, mp3 for compatibility,
    wav passthrough for editors."""
    if fmt == "m4a":
        codec = ["-c:a", "aac", "-b:a", "192k"]
    elif fmt == "mp3":
        codec = ["-c:a", "libmp3lame", "-q:a", "2"]
    else:
        codec = ["-c:a", "pcm_s16le"]
    return ["ffmpeg", "-y", "-i", str(input_path), *codec, str(output_path)]


# --- Export studio -------------------------------------------------------
# Full-parameter encode builders driven by the export studio panels. The
# pipeline-seeded exports (export_subtitles, export_audio) keep their own
# fixed-parameter builders above.

VIDEO_CODECS = {"libx264", "libx265"}
AUDIO_CODECS = {"aac", "libopus", "libmp3lame", "pcm_s16le"}
AUDIO_FORMAT_CODECS = {
    "m4a": "aac",
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "opus": "libopus",
}
AUDIO_TRACK_MODES = ("original", "dub", "none")
SUBTITLE_MODES = ("none", "target", "source", "bilingual")


@dataclass
class ExportVideoParams:
    """Video export panel, flattened. None on width/height/fps/sample_rate/
    channels means: keep the source value."""

    width: int | None = None
    height: int | None = None
    crf: int = 20
    audio_track: str = "original"
    subtitles: str = "none"
    subtitle_style: str | None = None
    video_codec: str = "libx264"
    video_bitrate_kbps: int | None = None
    fps: int | None = None
    audio_codec: str = "aac"
    audio_bitrate_kbps: int = 192
    sample_rate: int | None = None
    channels: int | None = None


@dataclass
class ExportAudioParams:
    """Audio export panel. `source` selects the dub mix or the original
    audio; the stage resolves it to a path."""

    fmt: str = "m4a"
    source: str = "dub"
    bitrate_kbps: int = 192
    sample_rate: int | None = None
    channels: int | None = None


def probe_media(input_path: Path) -> dict:
    """Duration, bit rate, resolution and audio streams in one ffprobe call.
    Missing fields come back as None rather than raising: a wav file has no
    resolution and a raw stream may report no bit rate."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(input_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise MediaError(f"ffprobe failed for {input_path}")
    try:
        data = json.loads(result.stdout)
    except ValueError as error:
        raise MediaError(f"unreadable probe output for {input_path}") from error
    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    def number(value, cast):
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_streams = [
        {
            "index": number(s.get("index"), int),
            "codec": s.get("codec_name"),
            "channels": number(s.get("channels"), int),
            "sample_rate": number(s.get("sample_rate"), int),
        }
        for s in streams
        if s.get("codec_type") == "audio"
    ]
    duration = number(fmt.get("duration"), float)
    if duration is None:
        raise MediaError(f"no duration in probe output for {input_path}")
    return {
        "duration": duration,
        "bit_rate": number(fmt.get("bit_rate"), int),
        "width": number(video.get("width"), int) if video else None,
        "height": number(video.get("height"), int) if video else None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_streams": audio_streams,
    }


def build_export_video_cmd(
    input_path: Path,
    output_path: Path,
    params: ExportVideoParams,
    *,
    dub_audio_path: Path | None = None,
    ass_path: Path | None = None,
    fonts_dir: Path | None = None,
) -> list[str]:
    """The container follows the output suffix, so callers pick mp4/mkv/webm
    by naming the file."""
    if params.video_codec not in VIDEO_CODECS:
        raise MediaError(f"unknown video codec: {params.video_codec}")
    if params.audio_track not in AUDIO_TRACK_MODES:
        raise MediaError(f"unknown audio track mode: {params.audio_track}")
    if params.audio_track == "dub" and dub_audio_path is None:
        raise MediaError("dub audio track needs a dub audio path")

    cmd = ["ffmpeg", "-y", "-i", str(input_path)]
    if params.audio_track == "dub":
        cmd += ["-i", str(dub_audio_path)]

    filters: list[str] = []
    if params.width and params.height:
        filters.append(f"scale={params.width}:{params.height}")
    if ass_path is not None:
        ass = f"ass={_escape_filter_path(ass_path)}"
        if fonts_dir is not None:
            ass += f":fontsdir={_escape_filter_path(fonts_dir)}"
        filters.append(ass)
    if filters:
        cmd += ["-vf", ",".join(filters)]

    if params.audio_track == "dub":
        cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    elif params.audio_track == "original":
        # The optional specifier keeps a silent source from failing the encode.
        cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
    else:
        cmd += ["-map", "0:v:0"]

    cmd += ["-c:v", params.video_codec]
    if params.video_bitrate_kbps:
        cmd += ["-b:v", f"{params.video_bitrate_kbps}k"]
    else:
        cmd += ["-crf", str(params.crf)]
    if params.fps:
        cmd += ["-r", str(params.fps)]

    if params.audio_track == "none":
        cmd.append("-an")
    else:
        if params.audio_codec not in AUDIO_CODECS:
            raise MediaError(f"unknown audio codec: {params.audio_codec}")
        cmd += ["-c:a", params.audio_codec]
        if params.audio_codec != "pcm_s16le":
            cmd += ["-b:a", f"{params.audio_bitrate_kbps}k"]
        if params.sample_rate:
            cmd += ["-ar", str(params.sample_rate)]
        if params.channels:
            cmd += ["-ac", str(params.channels)]
    cmd.append(str(output_path))
    return cmd


def build_export_audio_custom_cmd(
    input_path: Path, output_path: Path, params: ExportAudioParams
) -> list[str]:
    codec = AUDIO_FORMAT_CODECS.get(params.fmt)
    if codec is None:
        raise MediaError(f"unknown audio format: {params.fmt}")
    cmd = ["ffmpeg", "-y", "-i", str(input_path), "-vn", "-c:a", codec]
    if codec != "pcm_s16le":
        cmd += ["-b:a", f"{params.bitrate_kbps}k"]
    if params.sample_rate:
        cmd += ["-ar", str(params.sample_rate)]
    if params.channels:
        cmd += ["-ac", str(params.channels)]
    cmd.append(str(output_path))
    return cmd


# Bitrate doubles roughly every six CRF steps below the reference.
_CRF_REFERENCE = 23
_DEFAULT_SOURCE_BITRATE = 2_000_000
# Encode wall time as a multiple of media duration, measured loosely on
# consumer hardware. Only ever shown as an estimate.
_ETA_PER_SECOND = {"libx264": 0.6, "libx265": 1.8}
_ETA_SUBTITLE_BURN = 0.4
_ETA_AUDIO_PER_SECOND = 0.05


def estimate_export(
    probe: dict, params: ExportVideoParams | ExportAudioParams
) -> dict:
    """Rough output size and wall time. Size is bitrate times duration; for
    CRF encodes the video bitrate is extrapolated from the source bitrate by
    pixel count and CRF distance, which is an approximation, not a promise."""
    duration = float(probe.get("duration") or 0.0)
    if isinstance(params, ExportAudioParams):
        if params.fmt == "wav":
            sample_rate = params.sample_rate or _source_sample_rate(probe) or 48000
            channels = params.channels or _source_channels(probe) or 2
            size = sample_rate * channels * 2 * duration
        else:
            size = params.bitrate_kbps * 1000 * duration / 8
        eta = duration * _ETA_AUDIO_PER_SECOND
        return {"size_bytes": int(size), "eta_seconds": int(max(1, eta))}

    if params.video_bitrate_kbps:
        video_bitrate = params.video_bitrate_kbps * 1000
    else:
        source = probe.get("bit_rate") or _DEFAULT_SOURCE_BITRATE
        source_pixels = (probe.get("width") or 0) * (probe.get("height") or 0)
        target_pixels = (params.width or 0) * (params.height or 0)
        scale = (
            target_pixels / source_pixels
            if source_pixels and target_pixels
            else 1.0
        )
        video_bitrate = source * scale * 2 ** ((_CRF_REFERENCE - params.crf) / 6)
    audio_bitrate = (
        0 if params.audio_track == "none" else params.audio_bitrate_kbps * 1000
    )
    size = (video_bitrate + audio_bitrate) * duration / 8
    per_second = _ETA_PER_SECOND.get(params.video_codec, 1.0)
    if params.subtitles != "none":
        per_second += _ETA_SUBTITLE_BURN
    return {
        "size_bytes": int(size),
        "eta_seconds": int(max(1, duration * per_second)),
    }


def _source_sample_rate(probe: dict) -> int | None:
    streams = probe.get("audio_streams") or []
    return streams[0].get("sample_rate") if streams else None


def _source_channels(probe: dict) -> int | None:
    streams = probe.get("audio_streams") or []
    return streams[0].get("channels") if streams else None


DISK_HEADROOM = 1.5


def check_disk_space(target_dir: Path, need_bytes: int) -> tuple[bool, int]:
    """(enough, available). The headroom covers ffmpeg's temporary output
    plus the estimate being an estimate. Walks up to the nearest existing
    parent so a not-yet-created artifacts directory still reports its
    partition."""
    probe_dir = target_dir
    while not probe_dir.exists() and probe_dir.parent != probe_dir:
        probe_dir = probe_dir.parent
    try:
        available = shutil.disk_usage(probe_dir).free
    except OSError as error:
        raise MediaError(f"cannot read disk usage for {target_dir}") from error
    return available >= need_bytes * DISK_HEADROOM, available
