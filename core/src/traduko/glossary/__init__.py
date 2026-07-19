"""Glossary: named source -> target term tables injected into prompts.

The package layout keeps the model (`models`), file-backed store (`store`),
prompt helpers (`prompt`), and first-run migration (`migrate`) apart. The
public surface is re-exported here, including a `load_glossary` compatibility
shim that pre-v3_5 call sites still use.
"""
from __future__ import annotations

from pathlib import Path

from .models import GlossaryEntry, GlossaryTableMeta
from .prompt import format_for_prompt, relevant_entries
from .store import GlossaryStore


def load_glossary(root: Path, project: str) -> list[GlossaryEntry]:
    """Merged entries of every enabled glossary table.

    Compatibility shim for pre-v3_5 call sites: the per-task ``project`` is
    ignored and all enabled tables are merged (earlier table in manifest order
    wins). v3_5-03 replaces this with resolve_effective_glossary(task).
    """
    return GlossaryStore(root).enabled_merged()


__all__ = [
    "GlossaryEntry",
    "GlossaryTableMeta",
    "GlossaryStore",
    "format_for_prompt",
    "relevant_entries",
    "load_glossary",
]
