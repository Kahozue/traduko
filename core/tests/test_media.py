import subprocess
from pathlib import Path

import pytest

from traduko.media import (
    MediaError,
    build_atempo_cmd,
    build_extract_audio_cmd,
    build_extract_clip_cmd,
    build_extract_mix_audio_cmd,
    build_hardburn_cmd,
    build_mix_cmd,
    build_mix_filter_script,
    build_mux_cmd,
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


def test_extract_mix_audio_cmd_is_stereo_48k(tmp_path: Path) -> None:
    cmd = build_extract_mix_audio_cmd(tmp_path / "in.mp4", tmp_path / "orig.wav")
    assert cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[cmd.index("-ar") + 1] == "48000"


def test_extract_clip_cmd_seeks_before_input(tmp_path: Path) -> None:
    cmd = build_extract_clip_cmd(tmp_path / "in.mp4", 1.25, 4.0, tmp_path / "ref.wav")
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "1.250"
    assert cmd[cmd.index("-t") + 1] == "4.000"


def test_atempo_cmd(tmp_path: Path) -> None:
    cmd = build_atempo_cmd(tmp_path / "seg.wav", 1.234, tmp_path / "out.wav")
    assert cmd[cmd.index("-filter:a") + 1] == "atempo=1.234"


def test_mix_filter_script_ducks_and_delays() -> None:
    script = build_mix_filter_script(
        [0.5, 3.0], [(0.5, 2.0), (3.0, 4.0)], duck_volume=0.2
    )
    assert "volume=0.2:enable='between(t,0.500,2.000)+between(t,3.000,4.000)'" in script
    assert "[1:a]adelay=500|500[d0];" in script
    assert "[2:a]adelay=3000|3000[d1];" in script
    assert "amix=inputs=3:duration=first:normalize=0[out]" in script


def test_mix_filter_script_without_duck_windows_passes_audio_through() -> None:
    script = build_mix_filter_script([0.0], [], duck_volume=0.2)
    assert "[0:a]anull[duck];" in script
    assert "volume" not in script


def test_mix_cmd_lists_all_inputs_and_script(tmp_path: Path) -> None:
    cmd = build_mix_cmd(
        tmp_path / "orig.wav",
        [tmp_path / "a.wav", tmp_path / "b.wav"],
        tmp_path / "mix.filter",
        tmp_path / "mix.wav",
    )
    assert cmd.count("-i") == 3
    assert cmd[cmd.index("-filter_complex_script") + 1].endswith("mix.filter")
    assert cmd[cmd.index("-map") + 1] == "[out]"


def test_mux_cmd_copies_video_and_encodes_audio(tmp_path: Path) -> None:
    cmd = build_mux_cmd(tmp_path / "in.mp4", tmp_path / "mix.wav", tmp_path / "out.mp4")
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-shortest" in cmd


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_dub_media_chain_integration(tmp_path: Path) -> None:
    """atempo → mix → mux against real ffmpeg on generated media."""
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2",
            "-shortest", str(clip),
        ],
        check=True, capture_output=True,
    )
    orig = tmp_path / "orig.wav"
    run(build_extract_mix_audio_cmd(clip, orig))

    seg = tmp_path / "seg.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=1",
            str(seg),
        ],
        check=True, capture_output=True,
    )
    fast = tmp_path / "seg.tempo.wav"
    run(build_atempo_cmd(seg, 1.25, fast))
    assert probe_duration(fast) == pytest.approx(0.8, abs=0.1)

    script = tmp_path / "mix.filter"
    script.write_text(
        build_mix_filter_script([0.5], [(0.5, 1.3)], duck_volume=0.2),
        encoding="utf-8",
    )
    mix = tmp_path / "mix.wav"
    run(build_mix_cmd(orig, [fast], script, mix))
    assert probe_duration(mix) == pytest.approx(2.0, abs=0.3)

    dubbed = tmp_path / "dubbed.mp4"
    run(build_mux_cmd(clip, mix, dubbed))
    assert dubbed.exists() and dubbed.stat().st_size > 0


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


def test_build_silence_detect_and_chunk_cmds() -> None:
    from pathlib import Path

    from traduko.media import build_chunk_flac_cmd, build_silence_detect_cmd

    detect = build_silence_detect_cmd(Path("in.wav"))
    assert detect[0] == "ffmpeg"
    assert any("silencedetect" in part for part in detect)
    chunk = build_chunk_flac_cmd(Path("in.wav"), 12.5, 30.0, Path("out.flac"))
    assert "-ss" in chunk and "12.5" in chunk
    assert "-t" in chunk and "30.0" in chunk
    assert "flac" in chunk
    assert "16000" in chunk


def test_parse_silences_extracts_midpoints() -> None:
    from traduko.media import parse_silences

    stderr = "\n".join(
        [
            "[silencedetect @ 0x0] silence_start: 10.2",
            "[silencedetect @ 0x0] silence_end: 11.0 | silence_duration: 0.8",
            "noise line",
            "[silencedetect @ 0x0] silence_start: 55.5",
            "[silencedetect @ 0x0] silence_end: 56.5 | silence_duration: 1.0",
        ]
    )
    assert parse_silences(stderr) == [(10.2, 11.0), (55.5, 56.5)]


def test_plan_chunks_prefers_silence_boundaries() -> None:
    from traduko.media import plan_chunks

    # 30-minute file, silences near 9 and 19 minutes; target 10-minute
    # chunks with a 14-minute hard cap.
    silences = [(540.0, 541.0), (1140.0, 1141.0)]
    chunks = plan_chunks(1800.0, silences, target=600.0, hard_max=840.0)
    assert chunks[0] == (0.0, 540.5)
    assert chunks[1][0] == 540.5
    # Every chunk respects the hard cap and they tile the duration.
    assert all(end - start <= 840.0 for start, end in chunks)
    assert chunks[-1][1] == 1800.0
    for (a, b), (c, d) in zip(chunks, chunks[1:]):
        assert b == c


def test_plan_chunks_without_silence_cuts_at_hard_max() -> None:
    from traduko.media import plan_chunks

    chunks = plan_chunks(2000.0, [], target=600.0, hard_max=840.0)
    assert all(end - start <= 840.0 for start, end in chunks)
    assert chunks[-1][1] == 2000.0
    assert chunks[0] == (0.0, 840.0)


def test_plan_chunks_short_file_is_single_chunk() -> None:
    from traduko.media import plan_chunks

    assert plan_chunks(120.0, [], target=600.0, hard_max=840.0) == [(0.0, 120.0)]
