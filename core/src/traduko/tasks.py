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
from .artifacts import ArtifactStore
from .media import check_disk_space, media_kind_of
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
#
# export_subtitles deliberately sits outside the translate switch. It exports
# whatever transcript the pipeline holds, translated or not, so leaving it in
# would make "translation off" mean "no output at all" -- an av-default task
# would run ASR and then throw the result away. Outside the switch, the same
# task still lands a source-language subtitle file. export_transcript is out
# for the same reason.
SWITCH_STAGE_TYPES: dict[str, frozenset[str]] = {
    "translate": frozenset({"translate", "proofread", "translate_chunks", "qc_scan"}),
    "diarize": frozenset({"diarize"}),
    "dub": frozenset(
        {"tts_synthesize", "align_duration", "mix_audio", "mux", "export_audio"}
    ),
}

_AUDIO_DOMAIN_STAGES = frozenset({"export_transcript", "export_audio"})
_DOCUMENT_DOMAIN_STAGES = frozenset(
    {"ingest_document", "chunk", "translate_chunks", "export_document"}
)


def task_domain(record: TaskRecord) -> str:
    """Best-effort domain from the stage list, mirroring profile_kind: the
    record does not persist a kind, so the switch code infers it. A dubbed
    document grows an export_audio tail, so the document markers are checked
    first -- otherwise turning dubbing on would reclassify the task as audio
    and the next switch change would build the wrong dub group."""
    types = {stage.type for stage in record.stages}
    if types & _DOCUMENT_DOMAIN_STAGES:
        return "document"
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
    defaults = {
        "audio": (
            config.audio.translate_enabled,
            config.audio.diarize_enabled,
            config.audio.dub_enabled,
        ),
        "video": (
            config.dubbing.translate_enabled,
            config.dubbing.diarize_enabled,
            config.dubbing.dub_enabled,
        ),
        "document": (
            config.document.translate_enabled,
            None,
            config.document.dub_enabled,
        ),
    }.get(domain)
    if defaults is None:
        return None
    translate_default, diarize_default, dub_default = defaults
    switches = TaskSwitches()
    if types & SWITCH_STAGE_TYPES["translate"]:
        switches.translate = translate_default
    if diarize_default is not None and types & SWITCH_STAGE_TYPES["diarize"]:
        switches.diarize = diarize_default
    if types & SWITCH_STAGE_TYPES["dub"]:
        # A compose task is nothing but its dub group, so "dubbing off by
        # default" would skip away the whole point of it. The switch stays
        # visible, just on.
        switches.dub = True if "ingest_transcript" in types else dub_default
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


# Tail stage closing the appended dub group, per domain. A dubbed document
# has no video to mux into and no recording to mix under, so it ends the same
# way an audio task does: a rendered audio file.
DUB_GROUP_TAIL = {"video": "mux", "audio": "export_audio", "document": "export_audio"}

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


def dub_group_tail_for(record: TaskRecord, domain: str) -> str:
    """The stage type closing an appended dub group.

    mux needs a video to mux the dubbed track into. A video-domain task fed a
    subtitle file has none, so building a mux tail there guarantees a failure
    minutes in; it ends in export_audio instead, which is what dubbing a
    transcript actually produces.
    """
    if domain == "video":
        kind = media_kind_of(Path(record.input_path)) if record.input_path else None
        if kind != "video":
            return DUB_GROUP_TAIL["audio"]
    return DUB_GROUP_TAIL[domain]


def append_dub_stages(record: TaskRecord, domain: str) -> list[StageRecord]:
    """Append the full dub group to a task that has none, mirroring the
    seeded dub profiles (diarize pauses for speaker review).

    A document has no recording behind it: there are no voices to separate
    and no bed to mix the dub under, so its group is synthesis, layout and
    render. align_duration finds no timecodes on document segments and lays
    the clips end to end, which is what reading a document aloud means.
    """
    if domain == "document":
        added = [
            StageRecord(type="tts_synthesize", params={"voice_mode": "design"}),
            StageRecord(type="align_duration", params={"voice_mode": "design"}),
            StageRecord(type="export_audio"),
        ]
    else:
        added = [
            StageRecord(type="diarize", pause_after=True),
            StageRecord(type="tts_synthesize"),
            StageRecord(type="align_duration"),
            StageRecord(type="mix_audio"),
            StageRecord(type=dub_group_tail_for(record, domain)),
        ]
    record.stages.extend(added)
    return added


# Stage types that produce the transcript diarize annotates. Speaker
# separation slots in right after the last of them, ahead of translation.
_TRANSCRIPTION_STAGE_TYPES = ("asr", "segment")


def insert_diarize_stage(record: TaskRecord) -> StageRecord:
    """Insert speaker separation after the last transcription stage.

    spec 4-(3) makes diarize independent of dubbing, so an STT-only task can
    turn it on without dragging in the whole dub group. Raises when the task
    has nothing to diarize (a subtitle task has no audio).
    """
    last = -1
    for index, stage in enumerate(record.stages):
        if stage.type in _TRANSCRIPTION_STAGE_TYPES:
            last = index
    if last < 0:
        raise TaskActionError(
            "task has no transcription stage to separate speakers from",
            status=409,
        )
    stage = StageRecord(type="diarize", pause_after=True)
    record.stages.insert(last + 1, stage)
    return stage


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


class TaskActionError(Exception):
    """Rejected task action (create, switches, translation, dub params,
    export). Raised by the shared helpers so the HTTP endpoint, the CLI and
    the agent tool reject the same inputs with the same messages; status
    carries the HTTP mapping (404 not found, 400 missing input, 409 wrong
    state, 422 invalid fields) and the other entrances translate it to
    their own idiom (non-zero exit, ToolError)."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


class TaskCreateError(TaskActionError):
    """Rejected create-task input."""


def dub_enable_error(ws: "Workspace", record: TaskRecord) -> str | None:
    """The one hard condition for dubbing: a timestamped transcript, either
    already produced, guaranteed by the input format, or promised by a
    timestamped ASR engine still ahead. None when eligible."""
    from .artifacts import ArtifactStore
    from .asr.engines import engine_timestamps, resolve_engine

    # The condition exists so synthesis has original timings to fit the dub
    # to. A document never had any, and its group lays the clips end to end
    # instead of fitting them, so the requirement does not apply.
    if task_domain(record) == "document":
        return None

    artifacts = ArtifactStore(ws.store.task_dir(record.project, record.id))
    for name in ("segments.json", "translation.json"):
        try:
            artifacts.latest_path(name)
            return None
        except FileNotFoundError:
            pass
    try:
        asr = artifacts.read_latest_json("asr.json")
    except FileNotFoundError:
        asr = None
    if asr is not None:
        if asr.get("timestamps", True) is not False:
            return None
        return (
            "dub requires a timestamped transcript; the asr artifact has no "
            "timestamps — re-run transcription with a timestamped engine"
        )
    if Path(record.input_path).suffix.lower() in (".srt", ".vtt"):
        return None
    for stage in record.stages:
        if stage.type != "asr":
            continue
        engine_id = resolve_engine(stage.params, ws.config)
        if engine_id is None or engine_timestamps(engine_id):
            return None
        return (
            "dub requires a timestamped transcript, but asr engine "
            f"'{engine_id}' returns no timestamps"
        )
    return "dub requires a timestamped transcript"


def validate_switches_change(
    record: TaskRecord, changed: dict[str, bool | None]
) -> dict[str, bool]:
    """The field validation half of a switches change: drops unset fields and
    rejects an empty or ill-domained request. Kept apart from the apply half
    so each entrance can run its own is-the-task-busy guard in between."""
    applied = {name: value for name, value in changed.items() if value is not None}
    if not applied:
        raise TaskActionError("translate, diarize or dub required")
    if "translate" in applied and not any(
        stage.type in SWITCH_STAGE_TYPES["translate"] for stage in record.stages
    ):
        raise TaskActionError("task has no translate stage to switch")
    return applied


def apply_switches_change(
    ws: "Workspace", record: TaskRecord, changed: dict[str, bool]
) -> None:
    """Apply validated switch values: the dub hard condition, appending the
    dub group when a task never had one, then the status recalc. Saves."""
    if changed.get("dub"):
        error = dub_enable_error(ws, record)
        if error is not None:
            raise TaskActionError(error, status=409)
        if not any(stage.type == "tts_synthesize" for stage in record.stages):
            domain = task_domain(record)
            if domain not in DUB_GROUP_TAIL:
                raise TaskActionError(
                    "dub switch applies to video and audio tasks only"
                )
            added = append_dub_stages(record, domain)
            # The group ships with speaker separation, but that switch is the
            # user's, not the group's: a task that turned diarize off must not
            # get it (or its review checkpoint) back for enabling dubbing.
            # Synthesis falls back to a single voice when it finds no
            # speakers.json, so the skipped stage costs the dub nothing.
            existing = (record.switches or TaskSwitches()).diarize
            if existing is False and "diarize" not in changed:
                for stage in added:
                    if stage.type == "diarize":
                        stage.status = StageStatus.SKIPPED
                        stage.pause_after = False
    if changed.get("diarize") and not any(
        stage.type == "diarize" for stage in record.stages
    ):
        insert_diarize_stage(record)
    switches = record.switches or TaskSwitches()
    for name, value in changed.items():
        setattr(switches, name, value)
    record.switches = switches
    # Recalc only the switches this request set; the others already shaped
    # their stages when they were applied.
    recalc_stages_for_switches(record, TaskSwitches(**changed))
    ws.store.save(record)


def translate_stages_or_error(record: TaskRecord) -> list[StageRecord]:
    stages = [s for s in record.stages if s.type in TRANSLATE_STAGE_TYPES]
    if not stages:
        raise TaskActionError("task has no translate stage")
    return stages


def translation_settings(record: TaskRecord) -> dict:
    """Task-level translation settings, read off the first translate stage.
    A write covers every translate stage, so the first one speaks for all."""
    first = translate_stages_or_error(record)[0]
    return {
        "stage_type": first.type,
        "target_language": first.params.get("target_language") or "",
        "style": first.params.get("style") or "",
        "prompt_override": first.params.get("prompt_override") or "",
    }


def apply_translation_change(
    ws: "Workspace",
    record: TaskRecord,
    *,
    target_language: str | None = None,
    style: str | None = None,
    prompt_override: str | None = None,
) -> dict:
    """Write task-level translation settings onto every translate stage.
    None leaves a field as is; "" clears style / prompt_override. Saves and
    returns the updated settings."""
    stages = translate_stages_or_error(record)
    if target_language is not None and not target_language.strip():
        raise TaskActionError("target_language cannot be empty")
    for stage in stages:
        if target_language is not None:
            stage.params["target_language"] = target_language
        for name, value in (("style", style), ("prompt_override", prompt_override)):
            if value is None:
                continue
            if value:
                stage.params[name] = value
            else:
                stage.params.pop(name, None)
    if target_language is not None:
        # qc_scan reads the same language for its untranslated heuristic.
        for stage in record.stages:
            if stage.type == "qc_scan":
                stage.params["target_language"] = target_language
    ws.store.save(record)
    return translation_settings(record)


def dub_group_or_error(record: TaskRecord) -> list[StageRecord]:
    stages = dub_group_stages(record)
    if not stages:
        raise TaskActionError("task has no dub group")
    return stages


def _dub_stage(record: TaskRecord, stage_type: str) -> StageRecord | None:
    for stage in record.stages:
        if stage.type == stage_type:
            return stage
    return None


def dub_params_settings(record: TaskRecord) -> dict:
    tts = _dub_stage(record, "tts_synthesize")
    diarize = _dub_stage(record, "diarize")
    tts_params = tts.params if tts else {}
    diarize_params = diarize.params if diarize else {}
    return {
        "engine_id": tts_params.get("tts_engine"),
        "voice_mode": tts_params.get("voice_mode") or "clone",
        "instruction": tts_params.get("voice_instruction"),
        "cfg": tts_params.get("cfg"),
        "timesteps": tts_params.get("timesteps"),
        "seed": tts_params.get("seed"),
        "denoise": tts_params.get("denoise"),
        "preview_voice": tts_params.get("preview_voice"),
        "preview_rate": tts_params.get("preview_rate"),
        "dub_text": diarize_params.get("dub_text")
        or tts_params.get("dub_text")
        or "auto",
    }


def apply_dub_params_change(
    ws: "Workspace",
    record: TaskRecord,
    *,
    engine_id: str | None = None,
    voice_mode: str | None = None,
    instruction: str | None = None,
    cfg: float | None = None,
    timesteps: int | None = None,
    seed: int | None = None,
    denoise: float | None = None,
    preview_voice: str | None = None,
    preview_rate: int | None = None,
    dub_text: str | None = None,
) -> dict:
    """Write dub-studio parameters onto the dub stages. None leaves a field
    as is; "" clears engine_id / voice_mode / instruction / dub_text
    overrides. Saves and returns the updated settings."""
    # Deferred import: the stages package pulls this module back in.
    from .dubbing.engines import resolve_tts_engine

    if engine_id:
        try:
            resolve_tts_engine(engine_id)
        except Exception as error:  # DubbingError
            raise TaskActionError(str(error)) from error
    validate_voice_mode(voice_mode)
    validate_dub_text(dub_text)
    tts = _dub_stage(record, "tts_synthesize")
    if tts is not None:
        if engine_id is not None:
            if engine_id == "":
                tts.params.pop("tts_engine", None)
            else:
                tts.params["tts_engine"] = engine_id
        if cfg is not None:
            tts.params["cfg"] = cfg
        if timesteps is not None:
            tts.params["timesteps"] = timesteps
        if seed is not None:
            tts.params["seed"] = seed
        if denoise is not None:
            tts.params["denoise"] = denoise
        if preview_voice is not None:
            if preview_voice == "":
                tts.params.pop("preview_voice", None)
            else:
                tts.params["preview_voice"] = preview_voice
        if preview_rate is not None:
            tts.params["preview_rate"] = preview_rate
    # voice_mode / instruction / dub_text ride on the dub stages via the
    # existing override helpers so the same normalization rules apply.
    apply_voice_mode_override(record, voice_mode, instruction)
    apply_dub_text_override(record, dub_text)
    ws.store.save(record)
    return dub_params_settings(record)


def reset_dub_stages(
    ws: "Workspace", record: TaskRecord, from_: str = "synthesize"
) -> str:
    """Reset the dub group from tts_synthesize (or diarize) so the next run
    re-synthesizes. Saves; running the task is the caller's business."""
    group = dub_group_or_error(record)
    start_type = "diarize" if from_ == "diarize" else "tts_synthesize"
    if not any(stage.type == start_type for stage in group):
        raise TaskActionError(
            f"dub group has no {start_type} stage to reset from"
        )
    resetting = False
    for stage in group:
        if stage.type == start_type:
            resetting = True
        if resetting and stage.status != StageStatus.RUNNING:
            stage.status = StageStatus.PENDING
            stage.error = None
    # Redubbing from diarize un-skips speaker separation, so the switch has to
    # say so too. Leaving it off would put the task page's chip and the stage
    # that is about to run in direct contradiction.
    if start_type == "diarize" and record.switches is not None:
        record.switches.diarize = True
    if record.status == TaskStatus.COMPLETED:
        record.status = TaskStatus.PENDING
    ws.store.save(record)
    return start_type


def reset_for_retranslate(ws: "Workspace", record: TaskRecord) -> str:
    """Reset the translate stage and everything after it. Every downstream
    artifact and edit is regenerated on the next run; callers confirm first.
    Saves; running the task is the caller's business."""
    start = translate_stages_or_error(record)[0]
    resetting = False
    for stage in record.stages:
        if stage is start:
            resetting = True
        if resetting and stage.status != StageStatus.RUNNING:
            stage.status = StageStatus.PENDING
            stage.error = None
    if record.status == TaskStatus.COMPLETED:
        record.status = TaskStatus.PENDING
    ws.store.save(record)
    return start.type


def validate_export_request(record: TaskRecord, kind: str, params: dict) -> str:
    """Validate an export request and name its stage type. The params
    snapshot is parsed up front so a bad value is rejected here rather than
    failing the stage minutes into the queue; both panels encode from the
    task input, so a task whose input is not the right kind of media (a
    compose task's input is its transcript) is turned away too."""
    # Deferred import: the stages package pulls this module back in.
    from .stages.base import StageError
    from .stages.export import audio_params_from, video_params_from

    try:
        if kind == "video":
            video_params_from(params)
        elif kind == "audio":
            audio_params_from(params)
        else:
            raise TaskActionError(f"unknown export kind: {kind}")
    except StageError as error:
        raise TaskActionError(str(error)) from error
    if not record.input_path or not Path(record.input_path).exists():
        raise TaskActionError(f"task input file is missing: {record.input_path}")
    input_kind = media_kind_of(Path(record.input_path))
    if kind == "video" and input_kind != "video":
        raise TaskActionError(
            f"this task has no video to export: {record.input_path}"
        )
    if (
        kind == "audio"
        and params.get("source", "dub") == "original"
        and input_kind is None
    ):
        raise TaskActionError(
            "the original audio source needs a media input; "
            f"this task's input is {record.input_path}"
        )
    return "export_video" if kind == "video" else "export_audio_custom"


def export_source_path(
    ws: "Workspace", record: TaskRecord, kind: str, params: dict
) -> Path:
    """The media an export will actually read, mirroring the export stages.

    An audio export from the dub mix reads the dub-mix.wav artifact, not the
    task input: a compose task's input is a transcript, so probing it always
    fails and the estimate (and its disk check) silently drop out.
    """
    if kind == "audio" and params.get("source", "dub") == "dub":
        try:
            return ArtifactStore(
                ws.store.task_dir(record.project, record.id)
            ).latest_path("dub-mix.wav")
        except FileNotFoundError:
            raise TaskActionError(
                "no dub mix to export yet; finish the dubbing stages first"
            ) from None
    path = Path(record.input_path) if record.input_path else None
    if path is None or not path.exists():
        raise TaskActionError(f"task input file is missing: {record.input_path}")
    return path


def guard_export_disk_space(
    ws: "Workspace", record: TaskRecord, kind: str, params: dict
) -> None:
    """Refuse an export the disk cannot hold.

    spec 5-(3) puts this check before launching; keeping it in the core means
    HTTP, CLI and agent all get it, instead of it living in the GUI's estimate
    call alone. When the size cannot be estimated (no ffprobe, odd source) it
    falls back to twice the source file size rather than skipping the check.
    """
    # Deferred imports: media pulls the stage params, stages pull this module.
    from .media import MediaError, estimate_export, probe_media
    from .stages.base import StageError
    from .stages.export import audio_params_from, video_params_from

    source = export_source_path(ws, record, kind, params)
    try:
        parsed = video_params_from(params) if kind == "video" else audio_params_from(params)
        need = estimate_export(probe_media(source), parsed)["size_bytes"]
    except (MediaError, StageError):
        need = source.stat().st_size * 2
    artifacts_dir = ws.store.task_dir(record.project, record.id) / "artifacts"
    try:
        ok, available = check_disk_space(artifacts_dir, need)
    except MediaError:
        # Cannot read the partition: do not block the export on that.
        return
    if not ok:
        raise TaskActionError(
            f"not enough disk space for this export: needs about "
            f"{need // (1024 * 1024)} MB, {available // (1024 * 1024)} MB free",
            status=409,
        )


def append_export_stage(
    ws: "Workspace", record: TaskRecord, kind: str, params: dict
) -> str:
    """Append a validated one-off export stage. A fresh stage instance per
    export: the params snapshot and the numbered output keep earlier exports
    intact. Saves and returns the stage type."""
    stage_type = validate_export_request(record, kind, params)
    guard_export_disk_space(ws, record, kind, params)
    record.stages.append(
        StageRecord(type=stage_type, status=StageStatus.PENDING, params=params)
    )
    if record.status == TaskStatus.COMPLETED:
        record.status = TaskStatus.PENDING
    ws.store.save(record)
    return stage_type


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
        executor overwrites each artifact as its stage re-completes.

        A SKIPPED stage stays skipped. Rerunning means running the pipeline
        the user configured, and a stage is only skipped because a switch
        turned it off; resetting it to PENDING would quietly re-enable
        dubbing or speaker separation on the next run."""
        if record.status != TaskStatus.COMPLETED:
            raise ValueError(f"cannot rerun task in status {record.status.value}")
        for stage in record.stages:
            if stage.status == StageStatus.SKIPPED:
                continue
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
