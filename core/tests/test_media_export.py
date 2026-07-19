"""Export-studio media layer: probing, encode builders, estimation, disk."""
import json
import subprocess
from pathlib import Path

import pytest

from traduko.media import (
    ExportAudioParams,
    ExportVideoParams,
    MediaError,
    build_export_audio_custom_cmd,
    build_export_video_cmd,
    check_disk_space,
    estimate_export,
    ffmpeg_available,
    probe_media,
)

HAS_FFMPEG = ffmpeg_available()


PROBE_JSON = json.dumps(
    {
        "format": {"duration": "120.5", "bit_rate": "2500000"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "48000",
            },
        ],
    }
)


def _fake_probe(monkeypatch, stdout: str, returncode: int = 0) -> None:
    def fake_run(cmd, capture_output=True, text=True):
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_probe_media_reads_duration_bitrate_resolution_and_audio(monkeypatch) -> None:
    _fake_probe(monkeypatch, PROBE_JSON)
    probe = probe_media(Path("in.mp4"))
    assert probe["duration"] == pytest.approx(120.5)
    assert probe["bit_rate"] == 2500000
    assert probe["width"] == 1920
    assert probe["height"] == 1080
    assert probe["audio_streams"] == [
        {"index": 1, "codec": "aac", "channels": 2, "sample_rate": 48000}
    ]


def test_probe_media_without_video_stream_has_no_resolution(monkeypatch) -> None:
    _fake_probe(
        monkeypatch,
        json.dumps(
            {
                "format": {"duration": "10.0"},
                "streams": [
                    {
                        "index": 0,
                        "codec_type": "audio",
                        "codec_name": "mp3",
                        "channels": 1,
                        "sample_rate": "44100",
                    }
                ],
            }
        ),
    )
    probe = probe_media(Path("in.mp3"))
    assert probe["width"] is None and probe["height"] is None
    assert probe["bit_rate"] is None
    assert len(probe["audio_streams"]) == 1


def test_probe_media_raises_on_ffprobe_failure(monkeypatch) -> None:
    _fake_probe(monkeypatch, "", returncode=1)
    with pytest.raises(MediaError):
        probe_media(Path("missing.mp4"))


def test_export_video_cmd_scales_and_sets_crf(tmp_path: Path) -> None:
    params = ExportVideoParams(width=1280, height=720, crf=22)
    cmd = build_export_video_cmd(tmp_path / "in.mp4", tmp_path / "out.mp4", params)
    assert cmd[0] == "ffmpeg"
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1280:720" in vf
    assert cmd[cmd.index("-crf") + 1] == "22"
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[-1].endswith("out.mp4")


def test_export_video_cmd_source_resolution_omits_scale(tmp_path: Path) -> None:
    cmd = build_export_video_cmd(
        tmp_path / "in.mp4", tmp_path / "out.mp4", ExportVideoParams()
    )
    assert "-vf" not in cmd


def test_export_video_cmd_burns_subtitles_with_ass_filter(tmp_path: Path) -> None:
    ass = tmp_path / "sub's.ass"
    cmd = build_export_video_cmd(
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        ExportVideoParams(width=1280, height=720),
        ass_path=ass,
        fonts_dir=tmp_path / "fonts",
    )
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.startswith("scale=1280:720,ass=")
    assert "fontsdir=" in vf
    assert "'" not in vf.replace("\\'", "")


def test_export_video_cmd_dub_track_maps_second_input(tmp_path: Path) -> None:
    cmd = build_export_video_cmd(
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        ExportVideoParams(audio_track="dub"),
        dub_audio_path=tmp_path / "dub-mix.wav",
    )
    assert cmd.count("-i") == 2
    assert "0:v:0" in cmd and "1:a:0" in cmd
    assert "-shortest" in cmd


def test_export_video_cmd_dub_track_without_audio_path_raises(tmp_path: Path) -> None:
    with pytest.raises(MediaError):
        build_export_video_cmd(
            tmp_path / "in.mp4",
            tmp_path / "out.mp4",
            ExportVideoParams(audio_track="dub"),
        )


def test_export_video_cmd_no_audio_track_disables_audio(tmp_path: Path) -> None:
    cmd = build_export_video_cmd(
        tmp_path / "in.mp4", tmp_path / "out.mp4", ExportVideoParams(audio_track="none")
    )
    assert "-an" in cmd
    assert "-c:a" not in cmd


def test_export_video_cmd_advanced_fields(tmp_path: Path) -> None:
    params = ExportVideoParams(
        video_codec="libx265",
        video_bitrate_kbps=4000,
        fps=30,
        audio_codec="libopus",
        audio_bitrate_kbps=128,
        sample_rate=44100,
        channels=1,
    )
    cmd = build_export_video_cmd(tmp_path / "in.mp4", tmp_path / "out.mkv", params)
    assert cmd[cmd.index("-c:v") + 1] == "libx265"
    assert cmd[cmd.index("-b:v") + 1] == "4000k"
    assert "-crf" not in cmd
    assert cmd[cmd.index("-r") + 1] == "30"
    assert cmd[cmd.index("-c:a") + 1] == "libopus"
    assert cmd[cmd.index("-b:a") + 1] == "128k"
    assert cmd[cmd.index("-ar") + 1] == "44100"
    assert cmd[cmd.index("-ac") + 1] == "1"


def test_export_video_cmd_rejects_unknown_codec(tmp_path: Path) -> None:
    with pytest.raises(MediaError):
        build_export_video_cmd(
            tmp_path / "in.mp4",
            tmp_path / "out.mp4",
            ExportVideoParams(video_codec="rm-encoder"),
        )


@pytest.mark.parametrize(
    "fmt,codec",
    [
        ("m4a", "aac"),
        ("mp3", "libmp3lame"),
        ("wav", "pcm_s16le"),
        ("opus", "libopus"),
    ],
)
def test_export_audio_custom_cmd_maps_format_to_codec(
    tmp_path: Path, fmt: str, codec: str
) -> None:
    cmd = build_export_audio_custom_cmd(
        tmp_path / "in.wav",
        tmp_path / f"out.{fmt}",
        ExportAudioParams(fmt=fmt, bitrate_kbps=160, sample_rate=44100, channels=2),
    )
    assert cmd[cmd.index("-c:a") + 1] == codec
    assert cmd[cmd.index("-ar") + 1] == "44100"
    assert cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[-1].endswith(f"out.{fmt}")


def test_export_audio_custom_cmd_wav_ignores_bitrate(tmp_path: Path) -> None:
    cmd = build_export_audio_custom_cmd(
        tmp_path / "in.wav", tmp_path / "out.wav", ExportAudioParams(fmt="wav")
    )
    assert "-b:a" not in cmd


def test_export_audio_custom_cmd_rejects_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(MediaError):
        build_export_audio_custom_cmd(
            tmp_path / "in.wav", tmp_path / "out.aiff", ExportAudioParams(fmt="aiff")
        )


def test_estimate_export_video_size_follows_bitrate_times_duration() -> None:
    probe = {
        "duration": 100.0,
        "bit_rate": 2_000_000,
        "width": 1920,
        "height": 1080,
        "audio_streams": [],
    }
    params = ExportVideoParams(video_bitrate_kbps=1000, audio_bitrate_kbps=128)
    result = estimate_export(probe, params)
    # (1000 + 128) kbit/s over 100 s.
    assert result["size_bytes"] == pytest.approx(1128 * 1000 * 100 / 8, rel=0.01)
    assert result["eta_seconds"] > 0


def test_estimate_export_scales_bitrate_down_for_smaller_resolution() -> None:
    probe = {
        "duration": 60.0,
        "bit_rate": 4_000_000,
        "width": 1920,
        "height": 1080,
        "audio_streams": [],
    }
    full = estimate_export(probe, ExportVideoParams())
    scaled = estimate_export(probe, ExportVideoParams(width=1280, height=720))
    assert scaled["size_bytes"] < full["size_bytes"]


def test_estimate_export_lower_crf_means_bigger_file() -> None:
    probe = {
        "duration": 60.0,
        "bit_rate": 4_000_000,
        "width": 1920,
        "height": 1080,
        "audio_streams": [],
    }
    high_quality = estimate_export(probe, ExportVideoParams(crf=18))
    low_quality = estimate_export(probe, ExportVideoParams(crf=28))
    assert high_quality["size_bytes"] > low_quality["size_bytes"]


def test_estimate_export_without_audio_track_drops_audio_bitrate() -> None:
    probe = {
        "duration": 100.0,
        "bit_rate": 2_000_000,
        "width": 1920,
        "height": 1080,
        "audio_streams": [],
    }
    with_audio = estimate_export(probe, ExportVideoParams(video_bitrate_kbps=1000))
    muted = estimate_export(
        probe, ExportVideoParams(video_bitrate_kbps=1000, audio_track="none")
    )
    assert muted["size_bytes"] == pytest.approx(1000 * 1000 * 100 / 8, rel=0.01)
    assert muted["size_bytes"] < with_audio["size_bytes"]


def test_estimate_export_audio_params_uses_bitrate() -> None:
    probe = {
        "duration": 200.0,
        "bit_rate": None,
        "width": None,
        "height": None,
        "audio_streams": [{"index": 0, "codec": "aac", "channels": 2,
                           "sample_rate": 48000}],
    }
    result = estimate_export(probe, ExportAudioParams(fmt="m4a", bitrate_kbps=192))
    assert result["size_bytes"] == pytest.approx(192 * 1000 * 200 / 8, rel=0.01)


def test_estimate_export_wav_uses_pcm_size() -> None:
    probe = {
        "duration": 10.0,
        "bit_rate": None,
        "width": None,
        "height": None,
        "audio_streams": [],
    }
    result = estimate_export(
        probe, ExportAudioParams(fmt="wav", sample_rate=48000, channels=2)
    )
    assert result["size_bytes"] == pytest.approx(48000 * 2 * 2 * 10, rel=0.01)


def test_check_disk_space_requires_one_and_a_half_times_the_estimate(
    tmp_path: Path, monkeypatch
) -> None:
    import shutil as shutil_module

    from traduko import media

    def usage(_path):
        return shutil_module._ntuple_diskusage(1000, 700, 300)

    monkeypatch.setattr(media.shutil, "disk_usage", usage)
    ok, available = check_disk_space(tmp_path, 200)
    assert ok is True and available == 300
    # 250 * 1.5 = 375 > 300 available.
    assert check_disk_space(tmp_path, 250) == (False, 300)


def test_check_disk_space_walks_up_to_an_existing_directory(
    tmp_path: Path
) -> None:
    ok, available = check_disk_space(tmp_path / "not" / "created" / "yet", 1)
    assert ok is True and available > 0


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_probe_and_export_video_integration(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
            "-shortest", str(clip),
        ],
        check=True, capture_output=True,
    )
    probe = probe_media(clip)
    assert probe["width"] == 320 and probe["height"] == 240
    assert probe["audio_streams"]

    from traduko.media import run as run_media

    out = tmp_path / "out.mp4"
    run_media(
        build_export_video_cmd(
            clip, out, ExportVideoParams(width=160, height=120, crf=28)
        )
    )
    assert out.exists() and out.stat().st_size > 0
    assert probe_media(out)["width"] == 160
