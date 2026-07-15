"""Proofreading: AgentRunner's first application (design doc section 4).

The agent scans source/target pairs, fixes issues via tools, and
re-verifies in rounds until convergence. Every mutation goes through the
workspace so each edit carries a reason and lands in the run record.
"""
from __future__ import annotations

import json
from collections.abc import Callable

from ..glossary import GlossaryEntry
from .tools import AgentTool, ToolError, ToolRegistry


class ProofreadWorkspace:
    """Mutable working copy of translated segments plus the audit trail."""

    def __init__(self, segments: list[dict]) -> None:
        self.order = [seg["id"] for seg in segments]
        self.segments = {seg["id"]: dict(seg) for seg in segments}
        self.edits: list[dict] = []
        self.flags: list[dict] = []
        self.checked: set[int] = set()
        self.round = 1

    def start_round(self, round_number: int) -> None:
        self.round = round_number
        self.checked = set()

    def to_list(self) -> list[dict]:
        return [self.segments[seg_id] for seg_id in self.order]

    def _require(self, seg_id: int) -> dict:
        if seg_id not in self.segments:
            raise ToolError(f"unknown segment id: {seg_id}")
        return self.segments[seg_id]

    def read_range(self, start_id: int, end_id: int, context: int = 1) -> list[dict]:
        if start_id > end_id:
            raise ToolError("start_id must be <= end_id")
        positions = {seg_id: i for i, seg_id in enumerate(self.order)}
        if start_id not in positions or end_id not in positions:
            raise ToolError("start_id and end_id must be existing segment ids")
        lo = max(0, positions[start_id] - context)
        hi = min(len(self.order) - 1, positions[end_id] + context)
        rows: list[dict] = []
        for pos in range(lo, hi + 1):
            seg = self.segments[self.order[pos]]
            row = {"id": seg["id"], "source": seg["source"], "target": seg["target"]}
            if pos < positions[start_id] or pos > positions[end_id]:
                row["context"] = True
            else:
                self.checked.add(seg["id"])
            rows.append(row)
        return rows

    def edit(self, seg_id: int, new_target: str, reason: str) -> None:
        seg = self._require(seg_id)
        self.edits.append(
            {
                "id": seg_id, "before": seg["target"], "after": new_target,
                "reason": reason, "round": self.round,
            }
        )
        seg["target"] = new_target

    def flag(self, seg_id: int, note: str) -> None:
        self._require(seg_id)
        self.flags.append({"id": seg_id, "note": note, "round": self.round})

    def apply_targets(self, targets: dict[int, str], reason: str) -> None:
        for seg_id, text in targets.items():
            self.edit(seg_id, text, reason)

    def glossary_violations(self, entries: list[GlossaryEntry]) -> list[dict]:
        violations: list[dict] = []
        for seg_id in self.order:
            seg = self.segments[seg_id]
            for entry in entries:
                if entry.source in seg["source"] and entry.target not in seg["target"]:
                    violations.append(
                        {
                            "id": seg_id,
                            "source_term": entry.source,
                            "expected_target": entry.target,
                        }
                    )
        return violations


def build_proofread_tools(
    workspace: ProofreadWorkspace,
    glossary_entries: list[GlossaryEntry],
    retranslate: Callable[[int, int, str], dict[int, str]],
    on_progress: Callable[[], None],
) -> ToolRegistry:
    def read_segments(args: dict) -> str:
        rows = workspace.read_range(
            int(args["start_id"]), int(args["end_id"]),
            context=int(args.get("context", 1)),
        )
        on_progress()
        return json.dumps(rows, ensure_ascii=False)

    def check_glossary(args: dict) -> str:
        violations = workspace.glossary_violations(glossary_entries)
        if not violations:
            return "no glossary violations"
        return json.dumps(violations, ensure_ascii=False)

    def edit_segment(args: dict) -> str:
        workspace.edit(int(args["id"]), str(args["new_target"]), str(args["reason"]))
        return "ok"

    def flag_segment(args: dict) -> str:
        workspace.flag(int(args["id"]), str(args["note"]))
        return "ok"

    def retranslate_range(args: dict) -> str:
        start_id, end_id = int(args["start_id"]), int(args["end_id"])
        instruction = str(args.get("instruction", ""))
        targets = retranslate(start_id, end_id, instruction)
        workspace.apply_targets(
            targets, reason=f"retranslated: {instruction or 'low quality'}"
        )
        return json.dumps(
            [{"id": seg_id, "text": text} for seg_id, text in sorted(targets.items())],
            ensure_ascii=False,
        )

    registry = ToolRegistry()
    registry.register(
        AgentTool(
            name="read_segments",
            description=(
                "Read source/target pairs for segment ids start_id..end_id, "
                "plus neighbouring context rows marked with context=true."
            ),
            parameters={
                "start_id": {"type": "integer", "required": True, "description": "first id"},
                "end_id": {"type": "integer", "required": True, "description": "last id"},
                "context": {"type": "integer", "required": False, "description": "context rows on each side (default 1)"},
            },
            handler=read_segments,
        )
    )
    registry.register(
        AgentTool(
            name="check_glossary",
            description="Verify glossary terms were applied; returns violations.",
            parameters={},
            handler=check_glossary,
        )
    )
    registry.register(
        AgentTool(
            name="edit_segment",
            description="Rewrite one segment's translation; always give a reason.",
            parameters={
                "id": {"type": "integer", "required": True, "description": "segment id"},
                "new_target": {"type": "string", "required": True, "description": "replacement translation"},
                "reason": {"type": "string", "required": True, "description": "why this edit is needed"},
            },
            handler=edit_segment,
        )
    )
    registry.register(
        AgentTool(
            name="flag_segment",
            description="Mark a segment for human review when you are unsure.",
            parameters={
                "id": {"type": "integer", "required": True, "description": "segment id"},
                "note": {"type": "string", "required": True, "description": "what a human should check"},
            },
            handler=flag_segment,
        )
    )
    registry.register(
        AgentTool(
            name="retranslate_range",
            description="Retranslate segments start_id..end_id from scratch when quality is poor.",
            parameters={
                "start_id": {"type": "integer", "required": True, "description": "first id"},
                "end_id": {"type": "integer", "required": True, "description": "last id"},
                "instruction": {"type": "string", "required": False, "description": "style guidance for the retranslation"},
            },
            handler=retranslate_range,
        )
    )
    return registry
