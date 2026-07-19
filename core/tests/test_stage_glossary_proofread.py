import json
from pathlib import Path

import pytest

from traduko.artifacts import ArtifactStore
from traduko.config import CoreConfig, save_config
from traduko.events import EventBus
from traduko.glossary import GlossaryEntry, GlossaryStore
from traduko.models import StageRecord, TaskRecord
from traduko.stages import base, registry


def _context(tmp_path: Path, *, with_asr: bool = True) -> base.StageContext:
    task = TaskRecord(
        id="task-1",
        project="project-1",
        input_path="input.wav",
        profile="audio",
        stages=[StageRecord(type="glossary_proofread", params={"provider": "proof"})],
        created_at="2026-07-20T00:00:00+00:00",
        updated_at="2026-07-20T00:00:00+00:00",
    )
    artifacts = ArtifactStore(
        tmp_path / "projects" / task.project / "tasks" / task.id
    )
    if with_asr:
        artifacts.write_json(
            2,
            "asr.json",
            {
                "language": "zh-TW",
                "duration": 4.0,
                "timestamps": True,
                "segments": [
                    {"id": 1, "start": 0.0, "end": 2.0, "text": "我要用 Traduko"},
                    {"id": 2, "start": 2.0, "end": 4.0, "text": "普通句子"},
                ],
            },
        )
    return base.StageContext(
        task=task,
        stage_index=2,
        params=task.stages[0].params,
        artifacts=artifacts,
        data_root=tmp_path,
        emit_progress=lambda current, total: None,
        should_cancel=lambda: False,
        bus=EventBus(),
    )


def _write_glossary(tmp_path: Path, source: str = "Traduko") -> None:
    store = GlossaryStore(tmp_path)
    table = store.create_table("Terms", "general")
    store.write_entries(
        table.id, [GlossaryEntry(source=source, target="特拉杜科")]
    )


def test_glossary_proofread_corrects_only_matching_segments_and_writes_new_asr(
    tmp_path: Path,
) -> None:
    _write_glossary(tmp_path)
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={
                "proof": {
                    "type": "scripted",
                    "responses": [
                        json.dumps(
                            [{"id": 1, "text": "我要用特拉杜科"}],
                            ensure_ascii=False,
                        )
                    ],
                }
            }
        ),
    )
    ctx = _context(tmp_path)

    result = registry.create("glossary_proofread").run(ctx)

    assert result.artifacts == ["03-asr.json"]
    corrected = ctx.artifacts.read_latest_json("asr.json")
    assert corrected["segments"][0]["text"] == "我要用特拉杜科"
    assert corrected["segments"][1]["text"] == "普通句子"
    assert corrected["language"] == "zh-TW"
    assert corrected["duration"] == 4.0
    assert corrected["timestamps"] is True


def test_glossary_proofread_without_term_hit_writes_no_artifact(
    tmp_path: Path,
) -> None:
    _write_glossary(tmp_path, source="不存在的詞")
    ctx = _context(tmp_path)

    result = registry.create("glossary_proofread").run(ctx)

    assert result.artifacts == []
    assert not ctx.artifacts.path_for(3, "asr.json").exists()
    assert (
        ctx.artifacts.read_latest_json("asr.json")["segments"][0]["text"]
        == "我要用 Traduko"
    )


def test_glossary_proofread_requires_asr_artifact(tmp_path: Path) -> None:
    ctx = _context(tmp_path, with_asr=False)

    with pytest.raises(base.StageError, match="asr artifact"):
        registry.create("glossary_proofread").run(ctx)
