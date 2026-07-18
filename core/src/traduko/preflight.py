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
from pathlib import Path

from . import asrsetup
from .budget import BudgetMeter
from .config import (
    CoreConfig,
    load_config,
    real_provider_candidates,
    resolve_provider_name,
)
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


@register_check("extract_audio")
@register_check("hardburn")
def _check_ffmpeg(
    stage: StageRecord, root: Path, config: CoreConfig
) -> list[PreflightCheck]:
    if ffmpeg_available():
        return [PreflightCheck("ffmpeg", OK, "ffmpeg and ffprobe found")]
    return [PreflightCheck("ffmpeg", FAIL, "ffmpeg/ffprobe not found on PATH")]


@register_check("asr")
def _check_asr(
    stage: StageRecord, root: Path, config: CoreConfig
) -> list[PreflightCheck]:
    provider = stage.params.get("provider", "faster_whisper")
    if provider != "faster_whisper":
        return []
    if not asrsetup.package_available():
        return [
            PreflightCheck(
                "asr model", FAIL,
                "faster-whisper is not installed; install the asr extra: "
                "uv sync --extra asr",
            )
        ]
    model_size = stage.params.get("options", {}).get("model_size", "small")
    if not asrsetup.model_cached(model_size):
        return [
            PreflightCheck(
                "asr model", FAIL,
                f"model '{model_size}' is not downloaded yet",
            )
        ]
    return [
        PreflightCheck(
            "asr model", OK,
            f"faster-whisper installed; model '{model_size}' is cached",
        )
    ]


@register_check("translate")
@register_check("proofread")
@register_check("translate_chunks")
def _check_llm(
    stage: StageRecord, root: Path, config: CoreConfig
) -> list[PreflightCheck]:
    provider_name = resolve_provider_name(config, stage.params.get("provider"))
    if provider_name == "fake":
        if real_provider_candidates(config):
            # Real providers exist but none is selectable (several entries,
            # no default): the run would silently produce placeholder text.
            return [
                PreflightCheck(
                    "llm provider", FAIL,
                    "multiple llm providers configured but no default selected; "
                    "pick one in settings (default_provider)",
                )
            ]
        return [
            PreflightCheck(
                "llm provider", WARN,
                "no llm provider configured; the fake provider only produces "
                "placeholder text (add one in settings for real translation)",
            )
        ]
    provider_config = config.llm_providers.get(provider_name)
    if provider_config is None:
        return [
            PreflightCheck(
                "llm provider", FAIL,
                f"unknown llm provider: {provider_name} "
                "(define it under llm_providers in config/core.yaml)",
            )
        ]
    if provider_config.get("api_key"):
        return [
            PreflightCheck("llm provider", OK, f"{provider_name}: api key configured")
        ]
    env_name = provider_config.get("api_key_env")
    if env_name:
        if os.environ.get(env_name):
            return [
                PreflightCheck(
                    "llm provider", OK, f"{provider_name}: api key from {env_name}"
                )
            ]
        return [
            PreflightCheck(
                "llm provider", FAIL,
                f"{provider_name}: environment variable {env_name} is not set",
            )
        ]
    if provider_config.get("type") == "openai_compat":
        return [
            PreflightCheck(
                "llm provider", WARN,
                f"{provider_name}: no api key configured (fine for local endpoints)",
            )
        ]
    return [
        PreflightCheck("llm provider", OK, f"{provider_name}: no api key required")
    ]
