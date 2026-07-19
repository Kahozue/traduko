"""Glossary prompt helpers: filter to relevant terms and format for the LLM.

Behaviour is unchanged from the v1 single-file glossary; only the module
location moved when the glossary grew into a package.
"""
from __future__ import annotations

from collections.abc import Iterable

from .models import GlossaryEntry


def relevant_entries(
    entries: list[GlossaryEntry], texts: Iterable[str]
) -> list[GlossaryEntry]:
    corpus = list(texts)
    return [e for e in entries if any(e.source in text for text in corpus)]


def format_for_prompt(entries: list[GlossaryEntry]) -> str:
    if not entries:
        return "(none)"
    lines = []
    for entry in entries:
        line = f"{entry.source} -> {entry.target}"
        if entry.notes:
            line += f"  ({entry.notes})"
        lines.append(line)
    return "\n".join(lines)
