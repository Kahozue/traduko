from pathlib import Path

import pytest

from traduko.styles import SubtitleStyle, ass_color, format_ass_time, serialize_ass
from traduko.subtitles import Cue, SubtitleError, parse_ass, parse_subtitle

ASS_SAMPLE = """[Script Info]
Title: sample

[V4+ Styles]
Format: Name, Fontname, Fontsize
Style: Default,Arial,48

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,Hello {\\i1}there{\\i0}.
Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,Line one\\NLine two
"""


def test_ass_color() -> None:
    assert ass_color("#FFFFFF") == "&H00FFFFFF"
    assert ass_color("#112233") == "&H00332211"


def test_format_ass_time() -> None:
    assert format_ass_time(3661.25) == "1:01:01.25"


def test_serialize_ass_contains_style_and_dialogue() -> None:
    cues = [Cue(id=1, start=1.0, end=2.5, text="Hello\nthere")]
    style = SubtitleStyle(font_name="Noto Sans TC", font_size=52)
    out = serialize_ass(cues, style)
    assert "[V4+ Styles]" in out
    assert "Noto Sans TC" in out and "52" in out
    assert "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,Hello\\Nthere" in out


def test_parse_ass_strips_override_tags() -> None:
    cues = parse_ass(ASS_SAMPLE)
    assert len(cues) == 2
    assert cues[0].text == "Hello there."
    assert cues[0].start == 1.0 and cues[0].end == 2.5
    assert cues[1].text == "Line one\nLine two"


def test_parse_subtitle_dispatch(tmp_path: Path) -> None:
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    assert parse_subtitle(srt)[0].text == "hi"
    txt = tmp_path / "a.txt"
    txt.write_text("hello\n", encoding="utf-8")
    assert parse_subtitle(txt)[0].start is None
    with pytest.raises(SubtitleError):
        parse_subtitle(tmp_path / "a.docx")
