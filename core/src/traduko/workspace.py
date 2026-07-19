from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import CoreConfig, load_config
from .events import EventBus
from .glossary import migrate_legacy_glossaries
from .index import TaskIndex
from .paths import ensure_layout, resolve_data_root
from .seeds import ensure_defaults
from .tasks import TaskStore


@dataclass
class Workspace:
    root: Path
    config: CoreConfig
    store: TaskStore
    index: TaskIndex
    bus: EventBus

    @classmethod
    def open(cls, data_root: Path | None = None) -> "Workspace":
        root = ensure_layout(resolve_data_root(data_root))
        ensure_defaults(root)
        migrate_legacy_glossaries(root)
        index = TaskIndex(root)
        return cls(
            root=root,
            config=load_config(root),
            store=TaskStore(root, index=index),
            index=index,
            bus=EventBus(),
        )
