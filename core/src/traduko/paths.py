"""Data root resolution and on-disk layout.

Files under the data root are the source of truth for the whole system;
everything here must stay human-readable and self-describing.
"""
from __future__ import annotations

import os
from pathlib import Path

import platformdirs

ENV_DATA_ROOT = "TRADUKO_DATA_ROOT"
SUBDIRS = (
    "config",
    "profiles",
    "prompts",
    "glossaries",
    "projects",
    "sync",
    "budget",
    "skills",
    "proposals",
)


def resolve_data_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    env = os.environ.get(ENV_DATA_ROOT)
    if env:
        return Path(env)
    return Path(platformdirs.user_data_dir("traduko", appauthor=False))


def ensure_layout(root: Path) -> Path:
    for sub in SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root
