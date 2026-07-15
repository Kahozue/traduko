import json
from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.config import CoreConfig, save_config
from traduko.events import Event, EventBus
from traduko.models import StageRecord, TaskRecord, utc_now_iso
from traduko.stages import base, registry


TRANSLATION = {
    "source_language": "en",
    "target_language": "eo",
    "segments": [
        {"id": 1, "start": 1.0, "end": 2.0, "source": "hello", "target": "[T] hello"},
        {"id": 2, "start": 3.0, "end": 4.0, "source": "world", "target": "[T] world"},
    ],
}

AGENT_SCRIPT = [
    '{"tool": "read_segments", "arguments": {"start_id": 1, "end_id": 2, "context": 0}}',
    '{"tool": "edit_segment", "arguments": {"id": 1, "new_target": "Saluton", "reason": "natural greeting"}}',
    '{"tool": "end_round", "arguments": {"summary": "one fix"}}',
    '{"done": true, "summary": "clean"}',
]


def make_ctx(
    tmp_path: Path, params: dict, *, with_translation: bool = True
) -> tuple[base.StageContext, list[Event], Path]:
    task_dir = tmp_path / "projects" / "p" / "tasks" / "t1"
    artifacts = ArtifactStore(task_dir)
    artifacts.dir.mkdir(parents=True, exist_ok=True)
    if with_translation:
        artifacts.write_json(2, "translation.json", TRANSLATION)
    now = utc_now_iso()
    record = TaskRecord(
        id="t1", project="p", input_path="in.srt", profile="x",
        stages=[StageRecord(type="proofread", params=params)],
        created_at=now, updated_at=now,
    )
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(events.append)
    ctx = base.StageContext(
        task=record, stage_index=2, params=params, artifacts=artifacts,
        data_root=tmp_path, emit_progress=lambda current, total: None,
        should_cancel=lambda: False, bus=bus,
    )
    return ctx, events, task_dir


def test_intensity_off_is_a_no_op(tmp_path: Path) -> None:
    ctx, _, _ = make_ctx(tmp_path, {"intensity": "off"})
    result = registry.create("proofread").run(ctx)
    assert result.artifacts == []


def test_unknown_intensity_rejected(tmp_path: Path) -> None:
    ctx, _, _ = make_ctx(tmp_path, {"intensity": "extreme"})
    with pytest.raises(base.StageError):
        registry.create("proofread").run(ctx)


def test_requires_translation_artifact(tmp_path: Path) -> None:
    ctx, _, _ = make_ctx(tmp_path, {}, with_translation=False)
    with pytest.raises(base.StageError):
        registry.create("proofread").run(ctx)


def test_unknown_provider_rejected(tmp_path: Path) -> None:
    ctx, _, _ = make_ctx(tmp_path, {"provider": "nope"})
    with pytest.raises(base.StageError, match="unknown llm provider"):
        registry.create("proofread").run(ctx)


def test_scripted_proofread_writes_artifacts_and_events(tmp_path: Path) -> None:
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={"agent": {"type": "scripted", "responses": AGENT_SCRIPT}}
        ),
    )
    params = {
        "provider": "agent", "model": "test-model",
        "intensity": "deep", "max_rounds": 2,
    }
    ctx, events, task_dir = make_ctx(tmp_path, params)
    result = registry.create("proofread").run(ctx)
    assert result.artifacts == ["03-translation.json", "03-proofread-report.json"]

    translation = ctx.artifacts.read_json(3, "translation.json")
    assert translation["segments"][0]["target"] == "Saluton"
    assert translation["segments"][1]["target"] == "[T] world"

    report = ctx.artifacts.read_json(3, "proofread-report.json")
    assert report["converged"] is True and report["rounds"] == 2
    assert len(report["edits"]) == 1

    runs = list((task_dir / "agent-runs").glob("03-proofread-*.jsonl"))
    assert len(runs) == 1 and runs[0].stat().st_size > 0

    rounds = [e.data["round"] for e in events if e.type == "agent_round"]
    assert rounds == [1, 2]


def test_fake_provider_dry_run_converges(tmp_path: Path) -> None:
    ctx, _, _ = make_ctx(tmp_path, {"intensity": "fast"})
    result = registry.create("proofread").run(ctx)
    report = ctx.artifacts.read_json(3, "proofread-report.json")
    assert report["converged"] is True and report["edits"] == []
    translation = ctx.artifacts.read_json(3, "translation.json")
    assert translation["segments"][0]["target"] == "[T] hello"
    assert len(result.artifacts) == 2
