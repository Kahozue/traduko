"""Subtitle cue model and text-format parse/serialize (SRT/VTT/TXT)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class SubtitleError(Exception):
    pass


@dataclass
class Cue:
    id: int
    start: float | None
    end: float | None
    text: str


_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})")


def parse_srt_time(value: str) -> float:
    match = _TIME_RE.fullmatch(value.strip())
    if not match:
        raise SubtitleError(f"bad timestamp: {value!r}")
    hours, minutes, seconds, millis = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def format_srt_time(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _format_vtt_time(seconds: float) -> str:
    return format_srt_time(seconds).replace(",", ".")


def _parse_cue_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    for raw in re.split(r"\n\s*\n", text.strip()):
        lines = [line.rstrip() for line in raw.splitlines() if line.strip()]
        if lines:
            blocks.append(lines)
    return blocks


def _parse_timed(text: str, *, skip_header: bool) -> list[Cue]:
    if skip_header:
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("WEBVTT")
        )
    cues: list[Cue] = []
    for block in _parse_cue_blocks(text):
        arrow_index = next(
            (i for i, line in enumerate(block) if "-->" in line), None
        )
        if arrow_index is None:
            continue
        start_raw, _, end_raw = block[arrow_index].partition("-->")
        end_raw = end_raw.strip().split(" ")[0]
        body = "\n".join(block[arrow_index + 1 :])
        cues.append(
            Cue(
                id=len(cues) + 1,
                start=parse_srt_time(start_raw),
                end=parse_srt_time(end_raw),
                text=body,
            )
        )
    return cues


def parse_srt(text: str) -> list[Cue]:
    return _parse_timed(text, skip_header=False)


def parse_vtt(text: str) -> list[Cue]:
    return _parse_timed(text, skip_header=True)


def parse_txt(text: str) -> list[Cue]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [
        Cue(id=i + 1, start=None, end=None, text=line) for i, line in enumerate(lines)
    ]


def _require_timing(cues: list[Cue], fmt: str) -> None:
    for cue in cues:
        if cue.start is None or cue.end is None:
            raise SubtitleError(f"cue {cue.id} has no timing; cannot write {fmt}")


def serialize_srt(cues: list[Cue]) -> str:
    _require_timing(cues, "srt")
    parts = [
        f"{i + 1}\n{format_srt_time(c.start)} --> {format_srt_time(c.end)}\n{c.text}"
        for i, c in enumerate(cues)
    ]
    return "\n\n".join(parts) + "\n"


def serialize_vtt(cues: list[Cue]) -> str:
    _require_timing(cues, "vtt")
    parts = [
        f"{_format_vtt_time(c.start)} --> {_format_vtt_time(c.end)}\n{c.text}"
        for c in cues
    ]
    return "WEBVTT\n\n" + "\n\n".join(parts) + "\n"


def serialize_txt(cues: list[Cue]) -> str:
    return "\n".join(c.text for c in cues) + "\n"


def compose_bilingual(primary: str, secondary: str) -> str:
    return f"{primary}\n{secondary}"


_ASS_TAG_RE = re.compile(r"\{[^}]*\}")


def parse_ass(text: str) -> list[Cue]:
    cues: list[Cue] = []
    fields: list[str] | None = None
    in_events = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower() == "[events]":
            in_events = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_events = False
            continue
        if not in_events:
            continue
        if stripped.startswith("Format:"):
            fields = [f.strip().lower() for f in stripped[len("Format:") :].split(",")]
            continue
        if stripped.startswith("Dialogue:") and fields:
            values = stripped[len("Dialogue:") :].split(",", len(fields) - 1)
            row = dict(zip(fields, (v.strip() for v in values)))
            body = _ASS_TAG_RE.sub("", row.get("text", "")).replace("\\N", "\n")
            cues.append(
                Cue(
                    id=len(cues) + 1,
                    start=_parse_ass_time(row["start"]),
                    end=_parse_ass_time(row["end"]),
                    text=body,
                )
            )
    return cues


def _parse_ass_time(value: str) -> float:
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", value.strip())
    if not match:
        raise SubtitleError(f"bad ass timestamp: {value!r}")
    hours, minutes, seconds, cs = (int(g) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds + cs / 100


_PARSERS = {
    ".srt": parse_srt,
    ".vtt": parse_vtt,
    ".ass": parse_ass,
    ".txt": parse_txt,
}


def parse_subtitle(path: Path) -> list[Cue]:
    parser = _PARSERS.get(path.suffix.lower())
    if parser is None:
        raise SubtitleError(f"unsupported subtitle format: {path.suffix}")
    return parser(path.read_text(encoding="utf-8"))
