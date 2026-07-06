"""Glossary: source -> target term table injected into translation prompts.

CSV files with header source,target,notes,scope. One global file plus one
per project; project entries win on the same source term.
"""
from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GlossaryEntry:
    source: str
    target: str
    notes: str = ""
    scope: str = ""


def _read_csv(path: Path) -> list[GlossaryEntry]:
    if not path.exists():
        return []
    entries: list[GlossaryEntry] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            source = (row.get("source") or "").strip()
            target = (row.get("target") or "").strip()
            if not source or not target:
                continue
            entries.append(
                GlossaryEntry(
                    source=source,
                    target=target,
                    notes=(row.get("notes") or "").strip(),
                    scope=(row.get("scope") or "").strip(),
                )
            )
    return entries


def load_glossary(root: Path, project: str) -> list[GlossaryEntry]:
    merged: dict[str, GlossaryEntry] = {}
    for entry in _read_csv(root / "glossaries" / "global.csv"):
        if entry.scope in ("", project):
            merged[entry.source] = entry
    for entry in _read_csv(root / "glossaries" / f"{project}.csv"):
        merged[entry.source] = entry
    return list(merged.values())


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
