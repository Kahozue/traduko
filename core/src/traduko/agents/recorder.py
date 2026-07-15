"""Agent run records: human-readable JSONL under <task>/agent-runs/."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class AgentRunRecorder:
    def __init__(self, directory: Path, run_id: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{run_id}.jsonl"

    def record(self, kind: str, **data) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kind": kind,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
