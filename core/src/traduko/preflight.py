"""Task preflight: static checks before a run starts (design doc section 10).

Checks never mutate task state and nothing is persisted; callers decide
what to do with the report. Stage checks live in a registry keyed by
stage type, so new stage types plug in their own checks. Levels: ok,
warn (informational, never blocks), fail (blocks unless overridden).
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from .budget import BudgetMeter
from .config import CoreConfig, load_config
from .events import EventBus
from .media import ffmpeg_available
from .models import StageRecord, StageStatus, TaskRecord

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class PreflightCheck:
    name: str
    level: str  # ok | warn | fail
    message: str


@dataclass
class PreflightReport:
    checks: list[PreflightCheck]

    @property
    def ok(self) -> bool:
        return all(check.level != FAIL for check in self.checks)

    def failures(self) -> list[PreflightCheck]:
        return [check for check in self.checks if check.level == FAIL]


StageCheck = Callable[[StageRecord, Path, CoreConfig], list[PreflightCheck]]

STAGE_CHECKS: dict[str, StageCheck] = {}


def register_check(stage_type: str) -> Callable[[StageCheck], StageCheck]:
    def wrap(fn: StageCheck) -> StageCheck:
        STAGE_CHECKS[stage_type] = fn
        return fn

    return wrap


def _check_input(record: TaskRecord) -> PreflightCheck:
    path = Path(record.input_path)
    if path.exists():
        return PreflightCheck("input", OK, str(path))
    return PreflightCheck("input", FAIL, f"input not found: {path}")


def _check_budget(record: TaskRecord, root: Path, config: CoreConfig) -> PreflightCheck:
    remaining = BudgetMeter(root, EventBus(), config).remaining_usd(record.id)
    if remaining is None:
        return PreflightCheck("budget", OK, "uncapped")
    if remaining <= 0:
        return PreflightCheck("budget", FAIL, "budget exhausted (remaining $0.00)")
    return PreflightCheck("budget", OK, f"remaining ${remaining:.2f}")


def run_preflight(record: TaskRecord, root: Path) -> PreflightReport:
    config = load_config(root)
    checks = [_check_input(record), _check_budget(record, root, config)]
    for i, stage in enumerate(record.stages):
        if stage.status in (StageStatus.COMPLETED, StageStatus.SKIPPED):
            continue
        check_fn = STAGE_CHECKS.get(stage.type)
        if check_fn is None:
            continue
        for check in check_fn(stage, root, config):
            check.name = f"stage {i + 1} ({stage.type}): {check.name}"
            checks.append(check)
    return PreflightReport(checks)
