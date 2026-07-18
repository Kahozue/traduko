"""Duration-alignment decisions, pure so they are testable without ffmpeg.

VoxCPM has no explicit duration control, so fitting a synthesized clip
into its subtitle window is a loop: regenerate once with a faster-speech
instruction, then time-compress with atempo up to a quality cap, then
give up and record the overflow.
"""
from __future__ import annotations


def plan_segment(
    window: float,
    duration: float,
    *,
    tolerance: float = 1.1,
    max_tempo: float = 1.4,
    can_regen: bool = True,
) -> dict:
    allowed = window * tolerance
    if window <= 0:
        return {"action": "overflow", "tempo": max_tempo}
    if duration <= allowed:
        return {"action": "fit", "tempo": 1.0}
    if can_regen:
        return {"action": "regen", "tempo": 1.0}
    tempo = duration / allowed
    if tempo > max_tempo:
        return {"action": "overflow", "tempo": max_tempo}
    return {"action": "atempo", "tempo": round(tempo, 3)}
