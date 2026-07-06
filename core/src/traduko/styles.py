"""ASS subtitle style model and ASS document serialization.

The same style model drives file export and ffmpeg hardburn, so preview
and final render share one source of truth.
"""
from __future__ import annotations

from pydantic import BaseModel

from .subtitles import Cue, SubtitleError


class SubtitleStyle(BaseModel):
    name: str = "Default"
    font_name: str = "Arial"
    font_size: int = 48
    primary_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline: float = 2.0
    shadow: float = 0.0
    bold: bool = False
    alignment: int = 2
    margin_v: int = 40


def ass_color(hex_color: str) -> str:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise SubtitleError(f"bad color: {hex_color!r}")
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H00{b}{g}{r}".upper()


def format_ass_time(seconds: float) -> str:
    total_cs = round(seconds * 100)
    hours, rest = divmod(total_cs, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
"""


def serialize_ass(cues: list[Cue], style: SubtitleStyle) -> str:
    for cue in cues:
        if cue.start is None or cue.end is None:
            raise SubtitleError(f"cue {cue.id} has no timing; cannot write ass")
    style_line = (
        f"Style: {style.name},{style.font_name},{style.font_size},"
        f"{ass_color(style.primary_color)},{ass_color(style.outline_color)},"
        f"&H00000000,{-1 if style.bold else 0},0,1,{style.outline},{style.shadow},"
        f"{style.alignment},20,20,{style.margin_v},1"
    )
    events = [
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        text = cue.text.replace("\n", "\\N")
        events.append(
            f"Dialogue: 0,{format_ass_time(cue.start)},{format_ass_time(cue.end)},"
            f"{style.name},,0,0,0,,{text}"
        )
    return _ASS_HEADER + style_line + "\n\n" + "\n".join(events) + "\n"
