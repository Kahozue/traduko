"""Dubbing artifact documents: speakers.json, dub-manifest.json,
dub-timeline.json. Files are the source of truth; every document carries
schema_version."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Speaker(BaseModel):
    id: str
    label: str = ""
    ref_start: float = 0.0
    ref_end: float = 0.0
    ref_text: str = ""


class SpeakerAssignment(BaseModel):
    id: int
    speaker: str


class SpeakersDoc(BaseModel):
    schema_version: int = 1
    speakers: list[Speaker] = Field(default_factory=list)
    segments: list[SpeakerAssignment] = Field(default_factory=list)


class DubSegment(BaseModel):
    id: int
    speaker: str = ""
    file: str = ""
    duration: float = 0.0
    status: Literal["synthesized", "failed"] = "synthesized"
    error: str = ""


class DubManifestDoc(BaseModel):
    schema_version: int = 1
    segments: list[DubSegment] = Field(default_factory=list)


class TimelineSegment(BaseModel):
    id: int
    start: float
    window: float
    duration: float
    tempo: float = 1.0
    regenerated: bool = False
    file: str = ""
    status: Literal["fit", "atempo", "overflow", "failed"] = "fit"


class DubTimelineDoc(BaseModel):
    schema_version: int = 1
    # timed: clips are fitted into each segment's own window. sequential: the
    # transcript carries no timing, so clips are laid end to end and `note`
    # says why when the input was only partly timed.
    mode: Literal["timed", "sequential"] = "timed"
    note: str = ""
    segments: list[TimelineSegment] = Field(default_factory=list)
