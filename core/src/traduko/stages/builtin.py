from __future__ import annotations

from . import registry
from .base import StageContext, StageResult


@registry.register
class NoopStage:
    type = "noop"

    def run(self, ctx: StageContext) -> StageResult:
        ctx.emit_progress(1, 1)
        return StageResult()
