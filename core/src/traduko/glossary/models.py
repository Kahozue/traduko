"""Glossary data model: entries and per-table metadata."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GlossaryEntry:
    source: str
    target: str
    notes: str = ""
    category: str = ""


@dataclass
class GlossaryTableMeta:
    id: str
    name: str
    domain: str
    enabled: bool
    created_at: str
    updated_at: str
