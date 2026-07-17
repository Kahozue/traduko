"""Agent-driven pipeline stages. Proofread is AgentRunner's first user."""
from __future__ import annotations

from datetime import datetime, timezone

from .. import mcphub, skillhub
from ..agents.proofread import ProofreadSettings, run_proofread
from ..agents.recorder import AgentRunRecorder
from ..budget import BudgetMeter
from ..config import load_config
from ..events import Event
from ..glossary import load_glossary
from ..llm import LLMError
from ..prompts import load_template
from . import registry
from .base import StageContext, StageError, StageResult
from .common import resolve_llm


@registry.register
class ProofreadStage:
    type = "proofread"

    def run(self, ctx: StageContext) -> StageResult:
        intensity = ctx.params.get("intensity", "fast")
        if intensity not in ("off", "fast", "deep"):
            raise StageError(f"unknown proofread intensity: {intensity}")
        if intensity == "off":
            ctx.emit_progress(1, 1)
            return StageResult(artifacts=[])
        try:
            data = ctx.artifacts.read_latest_json("translation.json")
        except FileNotFoundError as error:
            raise StageError(
                "proofread stage requires a translation artifact"
            ) from error

        config = load_config(ctx.data_root)
        provider, model = resolve_llm(ctx.params, config)
        meter = BudgetMeter(ctx.data_root, ctx.bus, config)
        max_rounds = 1 if intensity == "fast" else int(ctx.params.get("max_rounds", 5))
        settings = ProofreadSettings(
            source_language=data.get("source_language", "unknown"),
            target_language=data.get("target_language", "unknown"),
            model=model,
            max_rounds=max_rounds,
            max_turns=int(ctx.params.get("max_turns", 60)),
            temperature=ctx.params.get("temperature"),
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        recorder = AgentRunRecorder(
            ctx.artifacts.dir.parent / "agent-runs",
            f"{ctx.stage_index + 1:02d}-proofread-{stamp}",
        )

        def on_round(round_number: int) -> None:
            ctx.bus.publish(
                Event(
                    type="agent_round",
                    task_id=ctx.task.id,
                    project=ctx.task.project,
                    data={"stage_index": ctx.stage_index, "round": round_number},
                )
            )

        try:
            result = run_proofread(
                data["segments"],
                settings,
                provider,
                meter,
                load_glossary(ctx.data_root, ctx.task.project),
                load_template(ctx.data_root, "proofread"),
                load_template(ctx.data_root, "translate"),
                project=ctx.task.project,
                task_id=ctx.task.id,
                recorder=recorder,
                emit_progress=ctx.emit_progress,
                on_round=on_round,
                extra_tools=[*mcphub.active_tools(), *skillhub.active_tools()],
                extra_context=skillhub.active_prompt_block(),
            )
        except LLMError as error:
            raise StageError(str(error)) from error

        translation_path = ctx.artifacts.write_json(
            ctx.stage_index + 1,
            "translation.json",
            {
                "source_language": settings.source_language,
                "target_language": settings.target_language,
                "segments": result.segments,
            },
        )
        report_path = ctx.artifacts.write_json(
            ctx.stage_index + 1, "proofread-report.json", result.report
        )
        return StageResult(artifacts=[translation_path.name, report_path.name])
