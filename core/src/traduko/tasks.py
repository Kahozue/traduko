"""TaskStore: task.json persistence. Files are the source of truth."""
from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from .fsutil import atomic_write_text
from .models import StageRecord, TaskRecord, new_task_id, utc_now_iso

if TYPE_CHECKING:
    from .index import TaskIndex

TASK_SUBDIRS = ("artifacts", "agent-runs", "logs")

# Stage types whose params carry an LLM provider/model override (the set of
# stages that call stages.common.resolve_llm, plus translate_pdf which
# forwards the provider to its engine).
LLM_STAGE_TYPES = frozenset(
    {"translate", "proofread", "translate_chunks", "translate_pdf"}
)


def apply_model_override(
    record: TaskRecord, provider: str | None, model: str | None
) -> None:
    """Write a per-task provider/model choice into every LLM stage's params.

    None leaves the field untouched; an empty string resets it ("fake"
    provider means: follow the configured default, no model key means: use
    the provider's default model)."""
    for stage in record.stages:
        if stage.type not in LLM_STAGE_TYPES:
            continue
        if provider is not None:
            stage.params["provider"] = provider or "fake"
        if model is not None:
            if model:
                stage.params["model"] = model
            else:
                stage.params.pop("model", None)


def apply_asr_engine_override(record: TaskRecord, engine: str | None) -> None:
    """Per-task ASR engine choice on every asr stage. None leaves things
    untouched; an empty string removes the override so the profile default
    (or the settings default) applies again."""
    if engine is None:
        return
    for stage in record.stages:
        if stage.type != "asr":
            continue
        if engine:
            stage.params["engine"] = engine
        else:
            stage.params.pop("engine", None)


VOICE_MODES = ("clone", "design", "preview")
DUB_STAGE_TYPES = frozenset({"diarize", "tts_synthesize", "align_duration"})
VOICE_INSTRUCTION_STAGE_TYPES = frozenset({"tts_synthesize", "align_duration"})


def apply_voice_mode_override(
    record: TaskRecord, mode: str | None, instruction: str | None = None
) -> None:
    """Per-task dubbing voice mode on the dub stages. None leaves things
    untouched; "" or "clone" removes the override (clone is the default).
    The voice-design instruction rides on the synthesizing stages, with the
    same None/"" semantics."""
    for stage in record.stages:
        if mode is not None and stage.type in DUB_STAGE_TYPES:
            if mode and mode != "clone":
                stage.params["voice_mode"] = mode
            else:
                stage.params.pop("voice_mode", None)
        if instruction is not None and stage.type in VOICE_INSTRUCTION_STAGE_TYPES:
            if instruction:
                stage.params["voice_instruction"] = instruction
            else:
                stage.params.pop("voice_instruction", None)


class TaskStore:
    def __init__(self, root: Path, index: "TaskIndex | None" = None) -> None:
        self.root = root
        self.index = index

    def task_dir(self, project: str, task_id: str) -> Path:
        return self.root / "projects" / project / "tasks" / task_id

    def create(
        self,
        *,
        project: str,
        input_path: str,
        profile_name: str,
        stages: list[StageRecord],
        name: str | None = None,
    ) -> TaskRecord:
        now = utc_now_iso()
        record = TaskRecord(
            id=new_task_id(),
            project=project,
            input_path=input_path,
            profile=profile_name,
            name=name or Path(input_path).stem,
            stages=stages,
            created_at=now,
            updated_at=now,
        )
        task_dir = self.task_dir(project, record.id)
        for sub in TASK_SUBDIRS:
            (task_dir / sub).mkdir(parents=True, exist_ok=True)
        self.save(record)
        return record

    def load(self, project: str, task_id: str) -> TaskRecord:
        path = self.task_dir(project, task_id) / "task.json"
        return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: TaskRecord) -> None:
        record.updated_at = utc_now_iso()
        path = self.task_dir(record.project, record.id) / "task.json"
        atomic_write_text(path, record.model_dump_json(indent=2))
        if self.index is not None:
            self.index.upsert(record)

    def delete(self, project: str, task_id: str) -> None:
        # Tolerate a missing directory so a stale index row (an orphan left by
        # an interrupted delete) still gets purged instead of wedging the task
        # in the list forever.
        task_dir = self.task_dir(project, task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir)
        if self.index is not None:
            self.index.delete(task_id)

    def move(self, record: TaskRecord, new_project: str) -> TaskRecord:
        src = self.task_dir(record.project, record.id)
        dst = self.task_dir(new_project, record.id)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        record.project = new_project
        self.save(record)
        return record

    def iter_tasks(self, project: str | None = None) -> Iterator[TaskRecord]:
        projects_dir = self.root / "projects"
        if not projects_dir.exists():
            return
        pattern = f"{project or '*'}/tasks/*/task.json"
        for path in sorted(projects_dir.glob(pattern)):
            yield TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
