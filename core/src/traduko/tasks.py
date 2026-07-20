"""TaskStore: task.json persistence. Files are the source of truth."""
from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from .asr.engines import stage_glossary_bias
from .config import CoreConfig
from .fsutil import atomic_write_text
from .glossary import task_glossary_for_new_task
from .media import media_kind_of
from .profiles import Profile, load_profile, profile_kind, stage_records_from
from .models import (
    StageRecord,
    StageStatus,
    TaskRecord,
    TaskStatus,
    TaskSwitches,
    new_task_id,
    utc_now_iso,
)

if TYPE_CHECKING:
    from .index import TaskIndex
    from .workspace import Workspace

TASK_SUBDIRS = ("artifacts", "agent-runs", "logs")

# Stage types whose params carry an LLM provider/model override (the set of
# stages that call stages.common.resolve_llm, plus translate_pdf which
# forwards the provider to its engine).
LLM_STAGE_TYPES = frozenset(
    {
        "translate",
        "proofread",
        "glossary_proofread",
        "translate_chunks",
        "translate_pdf",
    }
)


def ensure_glossary_proofread_stage(
    record: TaskRecord, config: CoreConfig
) -> StageRecord | None:
    """Synchronize glossary_proofread presence with ASR mode and capability."""
    asr_index = next(
        (index for index, stage in enumerate(record.stages) if stage.type == "asr"),
        None,
    )
    if asr_index is None:
        return None
    asr_stage = record.stages[asr_index]
    should_exist = record.glossary.asr_mode == "force" or (
        record.glossary.asr_mode == "auto"
        and not stage_glossary_bias(asr_stage.params, config)
    )
    existing = next(
        (stage for stage in record.stages if stage.type == "glossary_proofread"),
        None,
    )
    if should_exist:
        if existing is None:
            existing = StageRecord(type="glossary_proofread")
            record.stages.insert(asr_index + 1, existing)
        return existing
    if existing is not None:
        record.stages.remove(existing)
    return None


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


# Pipeline switches: which stage types each switch governs. The dub set names
# both domain tails (mux for video, export_audio for audio); a task only ever
# contains one of them, so matching by type needs no domain split.
SWITCH_STAGE_TYPES: dict[str, frozenset[str]] = {
    "translate": frozenset({"translate", "proofread", "export_subtitles"}),
    "diarize": frozenset({"diarize"}),
    "dub": frozenset(
        {"tts_synthesize", "align_duration", "mix_audio", "mux", "export_audio"}
    ),
}

_AUDIO_DOMAIN_STAGES = frozenset({"export_transcript", "export_audio"})


def task_domain(record: TaskRecord) -> str:
    """Best-effort domain from the stage list, mirroring profile_kind: the
    record does not persist a kind, and switches only need audio vs video."""
    types = {stage.type for stage in record.stages}
    return "audio" if types & _AUDIO_DOMAIN_STAGES else "video"


def stages_affected_by_switches(
    record: TaskRecord, switches: "TaskSwitches"
) -> dict[str, list[StageRecord]]:
    """Stages each explicitly-set switch governs, keyed by switch name."""
    affected: dict[str, list[StageRecord]] = {}
    for name, types in SWITCH_STAGE_TYPES.items():
        if getattr(switches, name) is None:
            continue
        affected[name] = [stage for stage in record.stages if stage.type in types]
    return affected


def recalc_stages_for_switches(record: TaskRecord, switches: "TaskSwitches") -> None:
    """Re-derive stage statuses from explicit switch values.

    Off: COMPLETED/PENDING/FAILED -> SKIPPED, artifacts stay on disk.
    On: SKIPPED -> PENDING (rerun overwrites artifacts); COMPLETED stays --
    re-enabling never resets work that was already done while enabled.
    Unaffected stages are untouched. A COMPLETED task with a stage back at
    PENDING returns to PENDING so it is runnable again."""
    for name, stages in stages_affected_by_switches(record, switches).items():
        enabled = getattr(switches, name)
        for stage in stages:
            if not enabled and stage.status != StageStatus.SKIPPED:
                stage.status = StageStatus.SKIPPED
                stage.error = None
            elif enabled and stage.status == StageStatus.SKIPPED:
                stage.status = StageStatus.PENDING
    if record.status == TaskStatus.COMPLETED and any(
        stage.status == StageStatus.PENDING for stage in record.stages
    ):
        record.status = TaskStatus.PENDING


def initial_switches_for_new_task(
    record: TaskRecord, config: CoreConfig
) -> TaskSwitches | None:
    """Initial switch values from the global pipeline defaults, per domain.
    Only switches whose stage group exists in the profile get a value; a task
    with nothing switchable keeps switches=None."""
    domain = task_domain(record)
    types = {stage.type for stage in record.stages}
    switches = TaskSwitches()
    if domain == "audio":
        if types & SWITCH_STAGE_TYPES["translate"]:
            switches.translate = config.audio.translate_enabled
        if types & SWITCH_STAGE_TYPES["diarize"]:
            switches.diarize = config.audio.diarize_enabled
        if types & SWITCH_STAGE_TYPES["dub"]:
            # A compose task is nothing but its dub group, so the audio
            # domain's "dubbing off by default" would skip away the whole
            # point of it. The switch stays visible, just on.
            switches.dub = (
                True
                if "ingest_transcript" in types
                else config.audio.dub_enabled
            )
    elif domain == "video":
        if types & SWITCH_STAGE_TYPES["diarize"]:
            switches.diarize = config.dubbing.diarize_enabled
    if switches == TaskSwitches():
        return None
    return switches


# Stage types whose params carry translation settings.
TRANSLATE_STAGE_TYPES = frozenset({"translate", "translate_chunks"})

# qc_scan has no translation settings of its own, but its untranslated-text
# heuristic keys off the same target language, so it has to move in step.
_TARGET_LANGUAGE_FOLLOWERS = frozenset({"qc_scan"})


def apply_translation_defaults(
    record: TaskRecord, kind: str, config: CoreConfig
) -> None:
    """Seed the task's translate stages from the domain defaults. Called once
    at creation from the shared create chain, so every entrance (HTTP, CLI,
    agent) applies them. style and prompt_override are only written when set,
    so an unconfigured domain leaves the profile's own params alone."""
    defaults = getattr(config.translation_defaults, kind, None)
    if defaults is None:
        return
    for stage in record.stages:
        if stage.type in TRANSLATE_STAGE_TYPES:
            stage.params["target_language"] = defaults.target_language
            if defaults.style:
                stage.params["style"] = defaults.style
            if defaults.prompt_override:
                stage.params["prompt_override"] = defaults.prompt_override
        elif stage.type in _TARGET_LANGUAGE_FOLLOWERS:
            stage.params["target_language"] = defaults.target_language


# Tail stage closing the appended dub group, per domain.
DUB_GROUP_TAIL = {"video": "mux", "audio": "export_audio"}

# Every stage type that belongs to a dub group (diarize through the domain
# tail). Used by the dub-studio params API and the redub reset range.
DUB_GROUP_TYPES = frozenset(
    {"diarize", "tts_synthesize", "align_duration", "mix_audio", "mux", "export_audio"}
)


def dub_group_stages(record: TaskRecord) -> list[StageRecord]:
    """The dub group stages on a task, in order. The dub group is the
    contiguous tail of dub-type stages (append_dub_stages extends to the
    end, and seeded dub profiles keep the group at the tail). Returns an
    empty list when the task has no dub group."""
    stages: list[StageRecord] = []
    for stage in reversed(record.stages):
        if stage.type in DUB_GROUP_TYPES:
            stages.append(stage)
        elif stages:
            break
    stages.reverse()
    return stages


def append_dub_stages(record: TaskRecord, domain: str) -> list[StageRecord]:
    """Append the full dub group to a task that has none, mirroring the
    seeded dub profiles (diarize pauses for speaker review)."""
    added = [
        StageRecord(type="diarize", pause_after=True),
        StageRecord(type="tts_synthesize"),
        StageRecord(type="align_duration"),
        StageRecord(type="mix_audio"),
        StageRecord(type=DUB_GROUP_TAIL[domain]),
    ]
    record.stages.extend(added)
    return added


DUB_TEXT_MODES = ("auto", "translation", "original")


def apply_dub_text_override(record: TaskRecord, dub_text: str | None) -> None:
    """Per-task dub text source on the dub stages. None leaves things
    untouched; "" or "auto" removes the override (auto is the default)."""
    if dub_text is None:
        return
    for stage in record.stages:
        if stage.type not in DUB_STAGE_TYPES:
            continue
        if dub_text and dub_text != "auto":
            stage.params["dub_text"] = dub_text
        else:
            stage.params.pop("dub_text", None)


class TaskCreateError(Exception):
    """Rejected create-task input. Raised by the shared create chain so the
    HTTP endpoint, the CLI and the agent tool reject the same inputs with the
    same messages; status carries the HTTP mapping (404 unknown profile, 400
    missing input, 422 invalid fields) and the other entrances translate it
    to their own idiom (non-zero exit, ToolError)."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def validate_voice_mode(mode: str | None) -> None:
    if mode and mode not in VOICE_MODES:
        raise TaskCreateError(f"voice_mode must be one of: {', '.join(VOICE_MODES)}")


def validate_dub_text(dub_text: str | None) -> None:
    if dub_text and dub_text not in DUB_TEXT_MODES:
        raise TaskCreateError(
            f"dub_text must be one of: {', '.join(DUB_TEXT_MODES)}"
        )


def _compose_transcript_params(root: Path, source: dict | None) -> tuple[dict, Path]:
    """(params.transcript, the file it resolves to) for an ingest_transcript
    stage. The source shape matches the stage's own contract in stages/av.py:
    rejecting a malformed source at creation beats failing the first run."""
    if not source:
        raise TaskCreateError("transcript is required for a compose profile")
    kind = source.get("kind")
    if kind == "file":
        if not source.get("path"):
            raise TaskCreateError("transcript.path is required for kind=file")
        path = Path(str(source["path"]))
        if not path.exists():
            raise TaskCreateError(f"transcript not found: {path}")
        return {"kind": "file", "path": str(path.resolve())}, path.resolve()
    if kind == "task":
        for field in ("project", "task_id", "file"):
            if not source.get(field):
                raise TaskCreateError(
                    f"transcript.{field} is required for kind=task"
                )
        file = str(source["file"])
        if Path(file).name != file:
            raise TaskCreateError(
                f"transcript.file must be a bare artifact name: {file}"
            )
        params = {
            "kind": "task",
            "project": str(source["project"]),
            "task_id": str(source["task_id"]),
            "file": file,
        }
        path = (
            root / "projects" / params["project"] / "tasks" / params["task_id"]
            / "artifacts" / file
        )
        if not path.exists():
            raise TaskCreateError(f"transcript artifact not found: {path}")
        return params, path.resolve()
    raise TaskCreateError(f"transcript.kind must be file or task, got: {kind}")


def _compose_inputs(
    root: Path, profile: Profile, transcript: dict | None, base_audio: str | None
) -> dict | None:
    """Validated compose inputs, or None for a profile that ingests no
    transcript. Runs before the task is created so a rejected request leaves
    nothing on disk."""
    if not any(stage.type == "ingest_transcript" for stage in profile.stages):
        return None
    transcript_params, resolved = _compose_transcript_params(root, transcript)
    bed = None
    if base_audio:
        bed_path = Path(base_audio)
        if not bed_path.exists():
            raise TaskCreateError(f"base audio not found: {bed_path}")
        bed = str(bed_path.resolve())
    return {"transcript": transcript_params, "base_audio": bed, "resolved": resolved}


def _apply_compose_inputs(record: TaskRecord, inputs: dict | None) -> None:
    if inputs is None:
        return
    for stage in record.stages:
        if stage.type == "ingest_transcript":
            stage.params["transcript"] = inputs["transcript"]
        elif stage.type == "mix_audio" and inputs["base_audio"]:
            stage.params["base_audio"] = inputs["base_audio"]


def create_task_from_profile(
    ws: "Workspace",
    *,
    profile: str,
    input_path: str = "",
    project: str | None = None,
    name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    asr_engine: str | None = None,
    voice_mode: str | None = None,
    voice_instruction: str | None = None,
    dub_text: str | None = None,
    transcript: dict | None = None,
    base_audio: str | None = None,
) -> TaskRecord:
    """The one create-task chain, shared by the HTTP endpoint, the CLI and
    the agent tool: profile load, compose-input validation, then the full
    post-create apply chain (glossary, domain translation defaults, per-task
    overrides, glossary proofread sync, initial pipeline switches). All
    validation runs before the task directory is created, so a rejected
    request leaves nothing on disk."""
    try:
        loaded = load_profile(ws.root, profile)
    except FileNotFoundError:
        raise TaskCreateError(f"profile not found: {profile}", status=404) from None
    validate_voice_mode(voice_mode)
    validate_dub_text(dub_text)
    compose = _compose_inputs(ws.root, loaded, transcript, base_audio)
    # An audio compose task has no media input at all, so the transcript
    # stands in as the input: preflight has a real file to check and the
    # default task name has something to read.
    if input_path:
        resolved_input = Path(input_path)
    elif compose is not None:
        resolved_input = compose["resolved"]
    else:
        raise TaskCreateError("input_path is required", status=400)
    if not resolved_input.exists():
        raise TaskCreateError(f"input not found: {resolved_input}", status=400)
    if any(stage.type in ("mux", "hardburn") for stage in loaded.stages) and (
        compose is not None and media_kind_of(resolved_input) != "video"
    ):
        raise TaskCreateError(
            f"this profile needs a video file as input: {resolved_input}"
        )
    record = ws.store.create(
        project=project or ws.config.default_project,
        input_path=str(resolved_input.resolve()),
        profile_name=profile,
        stages=stage_records_from(loaded),
        name=name,
    )
    kind = profile_kind(loaded)
    _apply_compose_inputs(record, compose)
    record.glossary = task_glossary_for_new_task(ws.root, kind)
    apply_translation_defaults(record, kind, ws.config)
    apply_asr_engine_override(record, asr_engine or None)
    apply_voice_mode_override(record, voice_mode or None, voice_instruction or None)
    apply_dub_text_override(record, dub_text or None)
    ensure_glossary_proofread_stage(record, ws.config)
    apply_model_override(record, provider or None, model or None)
    switches = initial_switches_for_new_task(record, ws.config)
    if switches is not None:
        record.switches = switches
        recalc_stages_for_switches(record, switches)
    ws.store.save(record)
    return record


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

    def reset_for_rerun(self, record: TaskRecord) -> None:
        """Reset a completed task so the whole pipeline runs again.

        Only a COMPLETED task can be rerun; a completed run is finished, so
        this is not a resume. Every stage goes back to PENDING with its error
        cleared and the task returns to PENDING. Products stay on disk: the
        executor overwrites each artifact as its stage re-completes."""
        if record.status != TaskStatus.COMPLETED:
            raise ValueError(f"cannot rerun task in status {record.status.value}")
        for stage in record.stages:
            stage.status = StageStatus.PENDING
            stage.error = None
        record.status = TaskStatus.PENDING
        self.save(record)

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
