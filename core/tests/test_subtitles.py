import pytest

from traduko.subtitles import (
    Cue,
    SubtitleError,
    compose_bilingual,
    format_srt_time,
    parse_srt,
    parse_srt_time,
    parse_txt,
    parse_vtt,
    serialize_srt,
    serialize_txt,
    serialize_vtt,
)

SRT_SAMPLE = """1
00:00:01,000 --> 00:00:02,500
Hello there.

2
00:00:03,000 --> 00:00:04,000
Second line
continues here.
"""

VTT_SAMPLE = """WEBVTT

00:00:01.000 --> 00:00:02.500
Hello there.

intro-cue
00:00:03.000 --> 00:00:04.000 align:start
Second line
"""


def test_parse_srt() -> None:
    cues = parse_srt(SRT_SAMPLE)
    assert len(cues) == 2
    assert cues[0] == Cue(id=1, start=1.0, end=2.5, text="Hello there.")
    assert cues[1].text == "Second line\ncontinues here."


def test_parse_vtt_skips_header_and_identifiers() -> None:
    cues = parse_vtt(VTT_SAMPLE)
    assert len(cues) == 2
    assert cues[0].start == 1.0
    assert cues[1].id == 2
    assert cues[1].text == "Second line"


def test_parse_txt_has_no_timing() -> None:
    cues = parse_txt("line one\n\nline two\n")
    assert [c.text for c in cues] == ["line one", "line two"]
    assert cues[0].start is None and cues[0].end is None


def test_srt_roundtrip() -> None:
    cues = parse_srt(SRT_SAMPLE)
    assert parse_srt(serialize_srt(cues)) == cues


def test_vtt_serialize_has_header() -> None:
    cues = [Cue(id=1, start=0.0, end=1.0, text="hi")]
    out = serialize_vtt(cues)
    assert out.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:01.000" in out


def test_serialize_timed_format_rejects_missing_timing() -> None:
    cues = [Cue(id=1, start=None, end=None, text="hi")]
    with pytest.raises(SubtitleError):
        serialize_srt(cues)
    with pytest.raises(SubtitleError):
        serialize_vtt(cues)
    assert serialize_txt(cues) == "hi\n"


def test_time_helpers() -> None:
    assert format_srt_time(3661.25) == "01:01:01,250"
    assert parse_srt_time("01:01:01,250") == pytest.approx(3661.25)


def test_compose_bilingual() -> None:
    assert compose_bilingual("target", "source") == "target\nsource"
