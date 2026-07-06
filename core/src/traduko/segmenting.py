"""Reshape raw ASR segments into subtitle-sized lines.

Deterministic text rules only; no model calls. Works on plain segment
dicts ({"id", "start", "end", "text"}) so artifacts stay JSON-native.
"""
from __future__ import annotations

import re

_SENTENCE_END = tuple("。！？!?…") + (".",)
_SPLIT_PUNCT_RE = re.compile(r"[。！？!?…\.]\s*|[，,;；]\s*")
_CJK_RE = re.compile(r"[　-鿿豈-﫿]")


def _ends_sentence(text: str) -> bool:
    return text.rstrip().endswith(_SENTENCE_END)


def _join(left: str, right: str) -> str:
    if _CJK_RE.search(left[-1:]) or _CJK_RE.search(right[:1]):
        return left + right
    return f"{left} {right}"


def _merge(segments: list[dict], max_chars: int, max_duration: float, merge_gap: float) -> list[dict]:
    merged: list[dict] = []
    for seg in segments:
        if merged:
            prev = merged[-1]
            candidate = _join(prev["text"], seg["text"])
            gap = seg["start"] - prev["end"]
            duration = seg["end"] - prev["start"]
            if (
                not _ends_sentence(prev["text"])
                and gap <= merge_gap
                and len(candidate) <= max_chars
                and duration <= max_duration
            ):
                prev["text"] = candidate
                prev["end"] = seg["end"]
                continue
        merged.append(dict(seg))
    return merged


def _split_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    cut = None
    for match in _SPLIT_PUNCT_RE.finditer(text):
        if match.end() < len(text) and match.end() <= max_chars:
            cut = match.end()
    if cut is None:
        space = text.rfind(" ", 1, max_chars + 1)
        cut = space + 1 if space > 0 else max_chars
    head, tail = text[:cut].strip(), text[cut:].strip()
    return [head] + _split_text(tail, max_chars)


def _split(segments: list[dict], max_chars: int) -> list[dict]:
    out: list[dict] = []
    for seg in segments:
        pieces = _split_text(seg["text"], max_chars)
        if len(pieces) == 1:
            out.append(seg)
            continue
        total_chars = sum(len(p) for p in pieces)
        duration = seg["end"] - seg["start"]
        cursor = seg["start"]
        for i, piece in enumerate(pieces):
            end = seg["end"] if i == len(pieces) - 1 else round(
                cursor + duration * len(piece) / total_chars, 3
            )
            out.append({"id": 0, "start": cursor, "end": end, "text": piece})
            cursor = end
    return out


def refine_segments(
    segments: list[dict],
    *,
    max_chars: int = 42,
    max_duration: float = 7.0,
    merge_gap: float = 0.4,
) -> list[dict]:
    cleaned = [
        {**seg, "text": re.sub(r"\s+", " ", seg["text"]).strip()}
        for seg in segments
        if seg["text"].strip()
    ]
    merged = _merge(cleaned, max_chars, max_duration, merge_gap)
    split = _split(merged, max_chars)
    return [{**seg, "id": i + 1} for i, seg in enumerate(split)]
