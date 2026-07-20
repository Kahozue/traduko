"""FastAPI service: the resident core every client talks to (design doc section 2).

Binds to 127.0.0.1 by default; GUI, CLI, Discord bot and webhooks are all
clients of this API, so each feature is implemented exactly once. Auth is
a bearer token generated on first start (config/api-token in the data
root); /health is the only unauthenticated route. One Workspace lives for
the whole app lifetime; handlers reach it through request.app.state.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os
import platform
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

import yaml

from .. import asrsetup
from ..asrsetup import AsrManager
from ..asr.macos import MacosAsrManager
from ..agents.assistant import (
    AssistantLLMError,
    AssistantUnavailable,
    clear_history as clear_assistant_history,
    load_history as load_assistant_history,
    run_assistant_message,
)
from ..artifacts import (
    ArtifactStore,
    ArtifactValidationError,
    validate_translation_payload,
)
from ..budget import BudgetMeter
from ..config import CoreConfig, load_config, save_config
from ..documents.model import DocTranslationDoc
from ..dubbing.models import SpeakersDoc
from ..dubbing.engines import TTS_ENGINES, resolve_tts_engine
from ..dubbing.client import DubbingError
from ..dubbing.preview import list_voices as list_say_voices, say_available
from ..dubbing.setup import DubbingManager
from ..eventlog import EventLogger
from ..executor import reset_stages_after_artifact
from ..stages.base import StageError
from ..stages.export import audio_params_from, video_params_from
from ..glossary import (
    GlossaryEntry,
    GlossaryStore,
    GlossaryTableMeta,
)
from ..glossary.store import _render_csv, _parse_csv
from ..events import Event
from ..media import (
    MediaError,
    check_disk_space,
    estimate_export,
    ffmpeg_available,
    media_kind_of,
    probe_media,
)
from ..pdfengine.setup import PdfManager
from .. import mcphub
from ..mcphub import MCPManager
from ..models import (
    InvalidTransition,
    StageRecord,
    StageStatus,
    TaskGlossary,
    TaskRecord,
    TaskStatus,
    TaskSwitches,
    transition,
)
from ..notify import Notifier, NotifyError, create_channel
from ..preflight import run_preflight
from .. import proposals, skillhub
from ..skillhub import SkillsManager, SkillValidationError
from ..styles import SubtitleStyle
from ..styles_render import render_style_frame
from ..tasks import (
    DUB_GROUP_TYPES,
    DUB_TEXT_MODES,
    TRANSLATE_STAGE_TYPES,
    TaskCreateError,
    VOICE_MODES,
    apply_asr_engine_override,
    apply_dub_text_override,
    apply_model_override,
    append_export_stage,
    export_source_path,
    apply_dub_params_change,
    apply_switches_change,
    apply_translation_change,
    apply_voice_mode_override,
    create_task_from_profile,
    dub_group_or_error,
    dub_group_stages,
    dub_params_settings,
    ensure_glossary_proofread_stage,
    reset_dub_stages,
    reset_for_retranslate,
    TaskActionError,
    translate_stages_or_error,
    translation_settings,
    validate_dub_text,
    validate_export_request,
    validate_switches_change,
    validate_voice_mode,
)
from ..sync.engine import (
    SyncConfigError,
    SyncEngine,
    SyncReport,
    create_target,
    list_peers,
    load_conflicts,
    load_state,
    resolve_conflict,
)
from ..workspace import Workspace
from .auth import load_or_create_token
from .broadcast import WsBroadcaster
from .syncsched import SyncScheduler
from .systemlog import setup_system_log
from .worker import TaskWorker


def require_token(request: Request) -> None:
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {request.app.state.token}"
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid or missing token")


router = APIRouter(dependencies=[Depends(require_token)])

ws_router = APIRouter()


@ws_router.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    token: str = websocket.app.state.token
    supplied = websocket.query_params.get("token", "")
    header = websocket.headers.get("authorization", "")
    if not (
        secrets.compare_digest(supplied, token)
        or secrets.compare_digest(header, f"Bearer {token}")
    ):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    broadcaster: WsBroadcaster = websocket.app.state.broadcaster
    client_id, queue = broadcaster.register()
    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unregister(client_id)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO instant; naive values are read as UTC. None on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/budget")
def get_budget(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    meter = BudgetMeter(ws.root, ws.bus, ws.config)
    # Optional [from, to) window over the ledger timestamps; absent bounds mean
    # all-time. Callers send ISO instants (the GUI resolves day/month/custom
    # presets in the user's local zone), so this endpoint stays a dumb filter.
    start = _parse_iso(request.query_params.get("from"))
    end = _parse_iso(request.query_params.get("to"))
    # Per-task and per-model spend within the window, with task names joined
    # from the index; tasks whose records are gone still show up under their id.
    spent: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    for path in sorted((ws.root / "budget").glob("ledger-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if start or end:
                when = _parse_iso(row.get("ts"))
                if when is None or (start and when < start) or (end and when >= end):
                    continue
            cost = float(row.get("cost_usd", 0.0))
            task_id = row.get("task_id", "")
            entry = spent.setdefault(
                task_id,
                {"task_id": task_id, "project": row.get("project", ""), "usd": 0.0},
            )
            entry["usd"] += cost
            model = row.get("model") or "unknown"
            agg = by_model.setdefault(model, {"usd": 0.0, "calls": 0})
            agg["usd"] += cost
            agg["calls"] += 1
    names = {row["id"]: row.get("name") for row in ws.index.list()}
    tasks = [
        {**entry, "name": names.get(entry["task_id"]), "usd": round(entry["usd"], 6)}
        for entry in spent.values()
    ]
    tasks.sort(key=lambda entry: entry["usd"], reverse=True)
    models = [
        {"model": model, "usd": round(agg["usd"], 6), "calls": agg["calls"]}
        for model, agg in by_model.items()
    ]
    models.sort(key=lambda entry: entry["usd"], reverse=True)
    return {
        "month_usd": meter.month_usage_usd(),
        "task_usd_limit": ws.config.budget.task_usd_limit,
        "monthly_usd_limit": ws.config.budget.monthly_usd_limit,
        "tasks": tasks[:50],
        "models": models,
    }


@router.get("/config")
def get_config(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    return ws.config.model_dump()


def _adopt_config(app: FastAPI, config: CoreConfig, notifier: Notifier) -> None:
    """Converge in-memory state on a config already persisted to disk:
    workspace config, notifier attachment and the active skills manager
    (disk-read based, so a rebuild costs nothing)."""
    ws: Workspace = app.state.workspace
    ws.config = config
    app.state.detach_notifier()
    app.state.detach_notifier = notifier.attach(ws.bus)
    skillhub.set_active(SkillsManager(ws.root, config.skills))
    # Engine managers read their interpreter override lazily, so pointing
    # them at the fresh value makes a saved python path take effect without
    # a core restart.
    app.state.dubbing.python_override = config.dubbing.python
    app.state.pdf.python_override = config.pdf.python


@router.put("/config")
def put_config(request: Request, body: dict) -> dict:
    ws: Workspace = request.app.state.workspace
    try:
        config = CoreConfig.model_validate(body)
    except ValidationError as error:
        raise HTTPException(
            status_code=422, detail=error.errors(include_url=False)
        ) from None
    if not config.default_project.strip():
        raise HTTPException(status_code=422, detail="default_project must not be empty")
    try:
        notifier = Notifier.from_config(config)
    except NotifyError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    save_config(ws.root, config)
    _adopt_config(request.app, config, notifier)
    return config.model_dump()


class NotifyTestRequest(BaseModel):
    channel: dict


class ProviderTestRequest(BaseModel):
    config: dict
    model: str | None = None


@router.post("/config/providers/test")
def test_provider(request: Request, body: ProviderTestRequest) -> dict:
    """Probe one llm_providers entry with a minimal chat call.

    The config is the same nested shape a provider takes under
    llm_providers (type, base_url, api_key/api_key_env, model). Delivery
    outcome is data, not a server error: unreachable endpoints, bad keys and
    unknown models all come back as {ok: false, error} so the settings panel
    classifies them into readable wording instead of hitting a 500."""
    from ..llm import ChatMessage, ChatRequest, LLMError, create_llm

    entry = dict(body.config)
    model = body.model or entry.pop("model", None) or ""
    entry.pop("model", None)
    if not model.strip():
        return {"ok": False, "error": "no model set: fill in a model to test"}
    try:
        provider = create_llm(entry)
    except LLMError as error:
        return {"ok": False, "error": str(error)}
    probe = ChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="ping")],
        # Small but not minimal: reasoning-capable models may reject or
        # zero-fill a 1-token budget, which would fail an otherwise healthy
        # endpoint.
        max_tokens=16,
    )
    try:
        provider.chat(probe)
    except LLMError as error:
        return {"ok": False, "error": str(error)}
    except Exception as error:  # noqa: BLE001 - outcome is data, never a 500
        return {"ok": False, "error": str(error)}
    return {"ok": True}


@router.post("/config/notifications/test")
def send_test_notification(request: Request, body: NotifyTestRequest) -> dict:
    try:
        channel = create_channel(body.channel)
    except (NotifyError, TypeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    event = Event(
        type="task_completed",
        task_id="test",
        project="traduko",
        data={"message": "test notification from settings"},
    )
    try:
        channel.send(event)
    except Exception as error:  # delivery outcome is data, not a server error
        return {"ok": False, "error": str(error)}
    return {"ok": True}


class TaskCreateRequest(BaseModel):
    # Optional only for an audio compose task, whose input is the transcript
    # itself: the caller cannot know an artifact's path, so the server fills
    # it in from the resolved transcript.
    input_path: str = ""
    profile: str
    project: str | None = None
    name: str | None = None
    # Optional per-task LLM override, written into every LLM stage's params.
    provider: str | None = None
    model: str | None = None
    # Optional per-task ASR engine override, written into asr stage params.
    asr_engine: str | None = None
    # Optional per-task dubbing voice mode (clone/design/preview) plus the
    # design-mode voice description, written into the dub stages' params.
    voice_mode: str | None = None
    voice_instruction: str | None = None
    # Optional dub text source (auto/translation/original) for the dub stages.
    dub_text: str | None = None
    # Compose input: where a compose profile's ingest_transcript stage reads
    # its transcript, plus an optional replacement mix bed for video-compose.
    transcript: dict | None = None
    base_audio: str | None = None


def _validate_voice_mode(mode: str | None) -> None:
    try:
        validate_voice_mode(mode)
    except TaskCreateError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from None


def _validate_dub_text(dub_text: str | None) -> None:
    try:
        validate_dub_text(dub_text)
    except TaskCreateError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from None


def _http(error: TaskActionError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=str(error))


def _load_task(ws: Workspace, project: str, task_id: str) -> TaskRecord:
    try:
        return ws.store.load(project, task_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"task not found: {project}/{task_id}"
        ) from None


@router.get("/tasks")
def list_tasks(
    request: Request, project: str | None = None, status: str | None = None
) -> list[dict]:
    ws: Workspace = request.app.state.workspace
    return ws.index.list(project=project, status=status)


@router.post("/tasks", status_code=201)
def create_task(request: Request, body: TaskCreateRequest) -> dict:
    ws: Workspace = request.app.state.workspace
    try:
        record = create_task_from_profile(
            ws,
            profile=body.profile,
            input_path=body.input_path,
            project=body.project,
            name=body.name,
            provider=body.provider,
            model=body.model,
            asr_engine=body.asr_engine,
            voice_mode=body.voice_mode,
            voice_instruction=body.voice_instruction,
            dub_text=body.dub_text,
            transcript=body.transcript,
            base_audio=body.base_audio,
        )
    except TaskCreateError as error:
        raise HTTPException(status_code=error.status, detail=str(error)) from None
    return record.model_dump()


@router.get("/tasks/{project}/{task_id}")
def show_task(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    return _load_task(ws, project, task_id).model_dump()


@router.get("/tasks/{project}/{task_id}/events")
def task_events(
    request: Request, project: str, task_id: str, limit: int = 100
) -> list[dict]:
    """Tail of the task's persisted event log (logs/events.jsonl)."""
    ws: Workspace = request.app.state.workspace
    _load_task(ws, project, task_id)
    log_path = (
        ws.root / "projects" / project / "tasks" / task_id / "logs" / "events.jsonl"
    )
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if line.strip()]
    return entries[-max(limit, 0) :]


class TaskUpdateRequest(BaseModel):
    name: str | None = None
    project: str | None = None
    # Per-task LLM override; "" resets to follow-default, None leaves as is.
    provider: str | None = None
    model: str | None = None
    # Per-task ASR engine; "" removes the override, None leaves as is.
    asr_engine: str | None = None
    # Per-task dubbing voice mode; ""/"clone" removes the override.
    voice_mode: str | None = None
    voice_instruction: str | None = None
    # Per-task dub text source; ""/"auto" removes the override.
    dub_text: str | None = None
    # Per-task glossary config; None leaves as is.
    glossary: TaskGlossary | None = None


@router.patch("/tasks/{project}/{task_id}")
def update_task(
    request: Request, project: str, task_id: str, body: TaskUpdateRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    if (
        body.name is None
        and body.project is None
        and body.provider is None
        and body.model is None
        and body.asr_engine is None
        and body.voice_mode is None
        and body.voice_instruction is None
        and body.dub_text is None
        and body.glossary is None
    ):
        raise HTTPException(
            status_code=422,
            detail="name, project, provider, model, asr_engine, "
            "voice_mode, voice_instruction, dub_text or glossary required",
        )
    _validate_voice_mode(body.voice_mode)
    _validate_dub_text(body.dub_text)
    name_changed = False
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be empty")
        record.name = name
        name_changed = True
    model_changed = False
    if (
        body.provider is not None
        or body.model is not None
        or body.asr_engine is not None
        or body.voice_mode is not None
        or body.voice_instruction is not None
        or body.dub_text is not None
        or body.glossary is not None
    ):
        worker: TaskWorker = request.app.state.worker
        if worker.is_active(project, task_id):
            raise HTTPException(status_code=409, detail="task is queued or running")
        apply_model_override(record, body.provider, body.model)
        apply_asr_engine_override(record, body.asr_engine)
        apply_voice_mode_override(record, body.voice_mode, body.voice_instruction)
        apply_dub_text_override(record, body.dub_text)
        if body.glossary is not None:
            record.glossary = body.glossary
        model_changed = True
    if body.project is not None:
        new_project = body.project.strip()
        if not new_project:
            raise HTTPException(status_code=422, detail="project must not be empty")
        if new_project != record.project:
            worker: TaskWorker = request.app.state.worker
            if worker.is_active(project, task_id):
                raise HTTPException(status_code=409, detail="task is queued or running")
            record = ws.store.move(record, new_project)
        elif name_changed or model_changed:
            ws.store.save(record)
    elif name_changed or model_changed:
        ws.store.save(record)
    return record.model_dump()


class TaskSwitchesRequest(BaseModel):
    # Each switch: True/False applies it, omitted leaves it as is.
    translate: bool | None = None
    diarize: bool | None = None
    dub: bool | None = None


@router.patch("/tasks/{project}/{task_id}/switches")
def patch_task_switches(
    request: Request, project: str, task_id: str, body: TaskSwitchesRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    try:
        changed = validate_switches_change(
            record,
            {"translate": body.translate, "diarize": body.diarize, "dub": body.dub},
        )
    except TaskActionError as error:
        raise _http(error) from None
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")
    try:
        apply_switches_change(ws, record, changed)
    except TaskActionError as error:
        raise _http(error) from None
    return record.model_dump()


class DubParamsRequest(BaseModel):
    # Each field: a value applies it, omitted (None) leaves it as is. Empty
    # string clears engine_id / voice_mode / instruction / dub_text overrides.
    engine_id: str | None = None
    voice_mode: str | None = None
    instruction: str | None = None
    cfg: float | None = None
    timesteps: int | None = None
    seed: int | None = None
    denoise: float | None = None
    preview_voice: str | None = None
    preview_rate: int | None = None
    dub_text: str | None = None


def _dub_group_or_422(record: TaskRecord) -> list:
    try:
        return dub_group_or_error(record)
    except TaskActionError as error:
        raise _http(error) from None


@router.get("/tasks/{project}/{task_id}/dub/params")
def get_dub_params(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    _dub_group_or_422(record)
    return dub_params_settings(record)


@router.patch("/tasks/{project}/{task_id}/dub/params")
def patch_dub_params(
    request: Request, project: str, task_id: str, body: DubParamsRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    _dub_group_or_422(record)
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")
    try:
        return apply_dub_params_change(
            ws,
            record,
            engine_id=body.engine_id,
            voice_mode=body.voice_mode,
            instruction=body.instruction,
            cfg=body.cfg,
            timesteps=body.timesteps,
            seed=body.seed,
            denoise=body.denoise,
            preview_voice=body.preview_voice,
            preview_rate=body.preview_rate,
            dub_text=body.dub_text,
        )
    except TaskActionError as error:
        raise _http(error) from None


class DubRedubRequest(BaseModel):
    from_: str = Field(alias="from", default="synthesize")

    model_config = {"populate_by_name": True}


@router.post("/tasks/{project}/{task_id}/dub/redub", status_code=202)
def dub_redub(
    request: Request, project: str, task_id: str, body: DubRedubRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    group = _dub_group_or_422(record)
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")
    try:
        reset_dub_stages(ws, record, body.from_)
    except TaskActionError as error:
        raise _http(error) from None
    return _enqueue_or_409(request, record)


class ExportRequest(BaseModel):
    kind: str = "video"
    params: dict = Field(default_factory=dict)


@router.post("/tasks/{project}/{task_id}/exports", status_code=202)
def create_export(
    request: Request, project: str, task_id: str, body: ExportRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    try:
        validate_export_request(record, body.kind, body.params)
    except TaskActionError as error:
        raise _http(error) from None
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")
    try:
        stage_type = append_export_stage(ws, record, body.kind, body.params)
    except TaskActionError as error:
        raise _http(error) from None
    return {
        **_enqueue_or_409(request, record),
        "stage_index": len(record.stages) - 1,
        "stage_type": stage_type,
    }


class ExportEstimateQuery(BaseModel):
    kind: str = "video"
    # Video panel.
    width: int | None = None
    height: int | None = None
    crf: int = 20
    audio_track: str = "original"
    subtitles: str = "none"
    video_codec: str = "libx264"
    video_bitrate_kbps: int | None = None
    fps: int | None = None
    audio_codec: str = "aac"
    audio_bitrate_kbps: int = 192
    # Audio panel.
    format: str = "m4a"
    source: str = "dub"
    bitrate_kbps: int = 192
    sample_rate: int | None = None
    channels: int | None = None


@router.get("/tasks/{project}/{task_id}/exports/estimate")
def estimate_task_export(
    request: Request,
    project: str,
    task_id: str,
    query: Annotated[ExportEstimateQuery, Query()],
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    fields = query.model_dump()
    try:
        validate_export_request(record, query.kind, fields)
        # An audio export from the dub mix encodes the mix, not the task
        # input: a compose task's input is a transcript that never probes.
        source = export_source_path(ws, record, query.kind, fields)
    except TaskActionError as error:
        raise _http(error) from None
    params = (
        video_params_from(fields)
        if query.kind == "video"
        else audio_params_from(fields)
    )
    try:
        probe = probe_media(source)
    except MediaError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    estimate = estimate_export(probe, params)
    artifacts_dir = ws.store.task_dir(project, task_id) / "artifacts"
    disk_ok, disk_available = check_disk_space(
        artifacts_dir, estimate["size_bytes"]
    )
    return {
        **estimate,
        "disk_ok": disk_ok,
        "disk_available": disk_available,
        "duration": probe["duration"],
        "width": probe["width"],
        "height": probe["height"],
    }


@router.delete("/tasks/{project}/{task_id}")
def delete_task(
    request: Request, project: str, task_id: str, force: bool = False
) -> dict:
    ws: Workspace = request.app.state.workspace
    # Deletable if it exists on disk or lingers in the index; the latter clears
    # an orphan row whose directory is already gone. Truly unknown ids 404.
    on_disk = (ws.store.task_dir(project, task_id) / "task.json").exists()
    indexed = any(row["id"] == task_id for row in ws.index.list())
    if not on_disk and not indexed:
        raise HTTPException(status_code=404, detail=f"task not found: {project}/{task_id}")
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        if not force:
            raise HTTPException(status_code=409, detail="task is queued or running")
        # Signal the executor to stop at its next checkpoint, then remove the
        # task directory. The running stage may still write briefly before it
        # sees the token; those writes hit a deleted path and are logged
        # harmlessly by the worker's exception handler.
        worker.cancel(project, task_id)
    ws.store.delete(project, task_id)
    return {"deleted": True}


@router.get("/tasks/{project}/{task_id}/preflight")
def preflight_task(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    report = run_preflight(record, ws.root)
    return {"ok": report.ok, "checks": [asdict(check) for check in report.checks]}


_RUNNABLE = {
    TaskStatus.PENDING,
    TaskStatus.PAUSED,
    TaskStatus.WAITING_REVIEW,
    TaskStatus.FAILED,
}


class RunRequest(BaseModel):
    skip_preflight: bool = False


def _gate_preflight(request: Request, record: TaskRecord, skip_preflight: bool) -> None:
    """Raise 409 with the failing checks unless preflight passes or is skipped.
    Leaves the record untouched, so a caller may retry after fixing the cause."""
    if skip_preflight:
        return
    ws: Workspace = request.app.state.workspace
    report = run_preflight(record, ws.root)
    if not report.ok:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "preflight failed",
                "checks": [asdict(check) for check in report.failures()],
            },
        )


def _enqueue_or_409(request: Request, record: TaskRecord) -> dict:
    worker: TaskWorker = request.app.state.worker
    if not worker.enqueue(record.project, record.id):
        raise HTTPException(status_code=409, detail="task already queued or running")
    return {"queued": True}


@router.post("/tasks/{project}/{task_id}/run", status_code=202)
def run_task(
    request: Request, project: str, task_id: str, body: RunRequest | None = None
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    if record.status not in _RUNNABLE:
        raise HTTPException(
            status_code=409,
            detail=f"cannot run task in status {record.status.value}",
        )
    _gate_preflight(request, record, bool(body and body.skip_preflight))
    return _enqueue_or_409(request, record)


@router.post("/tasks/{project}/{task_id}/rerun", status_code=202)
def rerun_task(
    request: Request, project: str, task_id: str, body: RunRequest | None = None
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    if record.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"cannot rerun task in status {record.status.value}",
        )
    # Preflight before the reset: a failing rerun leaves the completed task as
    # it was, so the client can restore the input or retry with skip_preflight
    # through this same endpoint (the task is still COMPLETED).
    _gate_preflight(request, record, bool(body and body.skip_preflight))
    ws.store.reset_for_rerun(record)
    return _enqueue_or_409(request, record)


@router.post("/tasks/{project}/{task_id}/cancel", status_code=202)
def cancel_task(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    worker: TaskWorker = request.app.state.worker
    record = _load_task(ws, project, task_id)
    if worker.cancel(project, task_id):
        return {"canceling": True}
    try:
        transition(record, TaskStatus.CANCELED)
    except InvalidTransition as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    ws.store.save(record)
    ws.bus.publish(
        Event(type="task_canceled", task_id=task_id, project=project, data={})
    )
    return {"canceled": True}


@router.post("/tasks/{project}/{task_id}/pause", status_code=202)
def pause_task(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    worker: TaskWorker = request.app.state.worker
    _load_task(ws, project, task_id)
    if not worker.pause(project, task_id):
        raise HTTPException(status_code=409, detail="task not queued or running")
    return {"pausing": True}


# --- task glossary entries ---------------------------------------------------


def _task_glossary_csv_path(ws: Workspace, project: str, task_id: str) -> Path:
    return ws.store.task_dir(project, task_id) / "glossary.csv"


@router.get("/tasks/{project}/{task_id}/glossary/entries")
def get_task_glossary_entries(
    request: Request, project: str, task_id: str
) -> dict:
    ws: Workspace = request.app.state.workspace
    _load_task(ws, project, task_id)
    path = _task_glossary_csv_path(ws, project, task_id)
    if not path.exists():
        return {"entries": []}
    parsed, _ = _parse_csv(path.read_text(encoding="utf-8"))
    entries = [
        {"source": e.source, "target": e.target, "notes": e.notes, "category": e.category}
        for e in parsed
    ]
    return {"entries": entries}


@router.put("/tasks/{project}/{task_id}/glossary/entries")
def put_task_glossary_entries(
    request: Request, project: str, task_id: str, body: GlossaryEntriesRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    _load_task(ws, project, task_id)
    entries = [
        GlossaryEntry(
            source=e.source.strip(),
            target=e.target.strip(),
            notes=e.notes.strip(),
            category=e.category.strip(),
        )
        for e in body.entries
        if e.source.strip() and e.target.strip()
    ]
    path = _task_glossary_csv_path(ws, project, task_id)
    from ..fsutil import atomic_write_text
    atomic_write_text(path, _render_csv(entries))
    return {"saved": True, "count": len(entries)}


# --- task glossary reapply ---------------------------------------------------


_VALID_REAPPLY_MODES = frozenset({"asr", "proofread", "translate"})


class TranslationRequest(BaseModel):
    # None leaves the field as is; "" clears style / prompt_override.
    target_language: str | None = None
    style: str | None = None
    prompt_override: str | None = None


@router.get("/tasks/{project}/{task_id}/translation")
def get_translation(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    try:
        return translation_settings(_load_task(ws, project, task_id))
    except TaskActionError as error:
        raise _http(error) from None


@router.patch("/tasks/{project}/{task_id}/translation")
def patch_translation(
    request: Request, project: str, task_id: str, body: TranslationRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    try:
        translate_stages_or_error(record)
    except TaskActionError as error:
        raise _http(error) from None
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")
    try:
        return apply_translation_change(
            ws,
            record,
            target_language=body.target_language,
            style=body.style,
            prompt_override=body.prompt_override,
        )
    except TaskActionError as error:
        raise _http(error) from None


@router.post("/tasks/{project}/{task_id}/retranslate", status_code=202)
def retranslate(request: Request, project: str, task_id: str) -> dict:
    """Reset the translate stage and everything after it, then run. Every
    downstream artifact and edit is regenerated; the UI confirms first."""
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")
    try:
        reset_from = reset_for_retranslate(ws, record)
    except TaskActionError as error:
        raise _http(error) from None
    return {**_enqueue_or_409(request, record), "reset_from": reset_from}


class ReapplyRequest(BaseModel):
    mode: str


@router.post("/tasks/{project}/{task_id}/glossary/reapply", status_code=202)
def reapply_glossary(
    request: Request, project: str, task_id: str, body: ReapplyRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    if body.mode not in _VALID_REAPPLY_MODES:
        raise HTTPException(status_code=422, detail=f"invalid mode: {body.mode}")
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")

    reset_from_type: str | None = None

    if body.mode == "asr":
        asr_index = next(
            (i for i, s in enumerate(record.stages) if s.type == "asr"), None
        )
        if asr_index is None:
            raise HTTPException(
                status_code=409, detail="no asr stage to reapply"
            )
        # Synchronize glossary_proofread presence with current asr_mode/bias.
        ensure_glossary_proofread_stage(record, ws.config)
        reset_from_type = "asr"

    elif body.mode == "proofread":
        asr_index = next(
            (i for i, s in enumerate(record.stages) if s.type == "asr"), None
        )
        if asr_index is None:
            raise HTTPException(
                status_code=409, detail="no asr stage to reapply"
            )
        # Ensure glossary_proofread exists right after asr.
        gp = next(
            (s for s in record.stages if s.type == "glossary_proofread"), None
        )
        if gp is None:
            record.stages.insert(asr_index + 1, StageRecord(type="glossary_proofread"))
        reset_from_type = "glossary_proofread"

    elif body.mode == "translate":
        trans_index = next(
            (
                i
                for i, s in enumerate(record.stages)
                if s.type in TRANSLATE_STAGE_TYPES
            ),
            None,
        )
        if trans_index is None:
            raise HTTPException(
                status_code=409, detail="no translate stage to reapply"
            )
        reset_from_type = record.stages[trans_index].type

    # Reset stages from the identified point onward.
    assert reset_from_type is not None
    reset_index = next(
        i for i, s in enumerate(record.stages) if s.type == reset_from_type
    )
    for stage in record.stages[reset_index:]:
        stage.status = StageStatus.PENDING
        stage.error = None
    record.status = TaskStatus.PENDING
    ws.store.save(record)
    return {**_enqueue_or_409(request, record), "reset_from": reset_from_type}


class AsrModelRequest(BaseModel):
    model: str = "small"


class AsrTestRequest(BaseModel):
    engine: str = "faster_whisper"
    model: str = ""
    locale: str = ""


class AsrAssetsRequest(BaseModel):
    locale: str = ""


@router.get("/asr/engines")
def asr_engines(request: Request, macos_probe: bool = False) -> dict:
    """Engine catalog plus per-engine readiness. The macOS helper is only
    compiled/probed when macos_probe is set (the section requests it when
    that engine is selected), so opening settings stays fast."""
    from ..asr.engines import ENGINES
    from ..asr.macos import helper_binary

    ws: Workspace = request.app.state.workspace
    config = ws.config
    macos_manager = request.app.state.macos_asr
    if macos_probe:
        macos_status = macos_manager.status()
    else:
        macos_status = {
            "platform_ok": platform.system() == "Darwin",
            "compiled": helper_binary(ws.root).exists(),
            "available": False,
            "probed": False,
            "transcriber_locales": [],
            "dictation_locales": [],
            "installed_locales": [],
            "assets_state": "idle",
            "assets_progress": 0.0,
            "assets_error": None,
            "error": None,
        }
    key_present = bool(
        config.asr.cloud_api_key
        or (
            config.asr.cloud_api_key_env
            and os.environ.get(config.asr.cloud_api_key_env)
        )
    )
    return {
        "engines": [
            {"id": engine.id, "kind": engine.kind, "timestamps": engine.timestamps}
            for engine in ENGINES
        ],
        "macos": macos_status,
        "cloud_key_present": key_present,
        "custom_ready": bool(config.asr.custom_base_url),
    }


@router.post("/asr/macos/assets", status_code=202)
def asr_macos_assets(request: Request, body: AsrAssetsRequest) -> dict:
    manager = request.app.state.macos_asr
    status = manager.status()
    if not status["available"]:
        raise HTTPException(
            status_code=409,
            detail=status.get("error") or "macOS speech engine is unavailable",
        )
    if not manager.start_assets(body.locale):
        raise HTTPException(status_code=409, detail="a download is already running")
    return {"downloading": True, "locale": body.locale}


@router.get("/asr/status")
def asr_status(request: Request, model: str = "small") -> dict:
    manager: AsrManager = request.app.state.asr
    return manager.status(model)


@router.post("/asr/download", status_code=202)
def asr_download(request: Request, body: AsrModelRequest | None = None) -> dict:
    manager: AsrManager = request.app.state.asr
    model = (body or AsrModelRequest()).model
    if not asrsetup.package_available():
        raise HTTPException(status_code=409, detail="asr engine is not available")
    if not manager.start_download(model):
        raise HTTPException(status_code=409, detail="a download is already running")
    return {"downloading": True, "model": model}


@router.post("/asr/test")
def asr_test(request: Request, body: AsrTestRequest | None = None) -> dict:
    payload = body or AsrTestRequest()
    ws: Workspace = request.app.state.workspace
    if payload.engine == "macos_native":
        return request.app.state.macos_asr.test(payload.locale)
    if payload.engine in (
        "openai_whisper",
        "openai_gpt4o",
        "openai_gpt4o_mini",
        "openai_gpt4o_diarize",
        "cloud_custom",
    ):
        return _asr_cloud_test(ws.config, payload.engine)
    # faster_whisper (default), backwards compatible with the old body shape.
    manager: AsrManager = request.app.state.asr
    model = payload.model or ws.config.asr.model
    status = manager.status(model)
    if not status["package"]:
        raise HTTPException(status_code=409, detail="asr engine is not available")
    if not status["cached"]:
        raise HTTPException(status_code=409, detail="model is not downloaded")
    return manager.test(model)


def _asr_cloud_test(config: CoreConfig, engine: str) -> dict:
    """Credential check: list models on the target endpoint."""
    import httpx

    if engine == "cloud_custom":
        base_url = config.asr.custom_base_url.rstrip("/")
        key = config.asr.custom_api_key or (
            os.environ.get(config.asr.custom_api_key_env)
            if config.asr.custom_api_key_env
            else ""
        )
        if not base_url:
            return {"ok": False, "error": "no base URL configured"}
    else:
        base_url = config.asr.cloud_base_url.rstrip("/")
        key = config.asr.cloud_api_key or (
            os.environ.get(config.asr.cloud_api_key_env)
            if config.asr.cloud_api_key_env
            else ""
        )
        if not key:
            return {"ok": False, "error": "no API key configured"}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        response = httpx.get(f"{base_url}/models", headers=headers, timeout=15)
    except httpx.HTTPError as error:
        return {"ok": False, "error": str(error)}
    if response.status_code != 200:
        return {
            "ok": False,
            "error": f"http {response.status_code}: {response.text[:200]}",
        }
    return {"ok": True}


@router.get("/dubbing/model/status")
def dubbing_model_status(request: Request) -> dict:
    manager: DubbingManager = request.app.state.dubbing
    return manager.model_status()


@router.post("/dubbing/model/download", status_code=202)
def dubbing_model_download(request: Request) -> dict:
    manager: DubbingManager = request.app.state.dubbing
    if not manager.start_model_download():
        raise HTTPException(status_code=409, detail="a download is already running")
    return {"downloading": True}


@router.get("/dubbing/status")
def dubbing_status(request: Request) -> dict:
    manager: DubbingManager = request.app.state.dubbing
    return manager.status()


@router.get("/dub/engines")
def dub_engines() -> dict:
    # Static catalog backing the dubbing studio's engine menu. Placeholder
    # engines are listed (with available=False) so the UI can render them as
    # "coming soon"; the executor rejects them via resolve_tts_engine.
    return {
        "engines": [
            {
                "id": engine.id,
                "kind": engine.kind,
                "voice_modes": list(engine.voice_modes),
                "available": engine.available,
            }
            for engine in TTS_ENGINES
        ]
    }


@router.get("/dub/voices")
def dub_voices() -> dict:
    """System voices for the say preview engine's voice picker.

    Empty rather than an error when say is unavailable (any non-macOS host)
    or the listing fails: the studio then falls back to letting the engine
    pick a voice for the segment's language, which is the default anyway.
    """
    if not say_available():
        return {"voices": []}
    try:
        voices = list_say_voices()
    except DubbingError:
        return {"voices": []}
    return {"voices": [{"name": v.name, "locale": v.locale} for v in voices]}


@router.post("/dubbing/install", status_code=202)
def dubbing_install(request: Request) -> dict:
    manager: DubbingManager = request.app.state.dubbing
    if not manager.start_install():
        status = manager.status()
        if status["installing"]:
            raise HTTPException(
                status_code=409, detail="an install is already running"
            )
        raise HTTPException(
            status_code=409, detail=status["error"] or "cannot install engine"
        )
    return {"installing": True}


@router.post("/dubbing/test")
def dubbing_test(request: Request) -> dict:
    manager: DubbingManager = request.app.state.dubbing
    if not manager.status()["installed"]:
        raise HTTPException(status_code=409, detail="dubbing engine is not installed")
    return manager.test()


@router.get("/pdf/status")
def pdf_status(request: Request) -> dict:
    manager: PdfManager = request.app.state.pdf
    return manager.status()


@router.post("/pdf/install", status_code=202)
def pdf_install(request: Request) -> dict:
    manager: PdfManager = request.app.state.pdf
    if not manager.start_install():
        status = manager.status()
        if status["installing"]:
            raise HTTPException(
                status_code=409, detail="an install is already running"
            )
        raise HTTPException(
            status_code=409, detail=status["error"] or "cannot install engine"
        )
    return {"installing": True}


@router.post("/pdf/test")
def pdf_test(request: Request) -> dict:
    manager: PdfManager = request.app.state.pdf
    if not manager.status()["installed"]:
        raise HTTPException(status_code=409, detail="pdf engine is not installed")
    return manager.test()


@router.get("/mcp/candidates")
def mcp_candidates(request: Request) -> list[dict]:
    ws: Workspace = request.app.state.workspace
    return mcphub.candidate_entries(ws.root)


@router.get("/mcp/status")
def mcp_status(request: Request) -> list[dict]:
    manager: MCPManager | None = getattr(request.app.state, "mcp", None)
    return manager.status() if manager is not None else []


@router.post("/mcp/reload")
async def mcp_reload(request: Request) -> list[dict]:
    """Rebuild the manager from the current config; the UI calls this after
    saving mcp_servers changes."""
    ws: Workspace = request.app.state.workspace
    old: MCPManager | None = getattr(request.app.state, "mcp", None)
    mcphub.set_active(None)
    if old is not None:
        await old.stop()
    manager = MCPManager(load_config(ws.root).mcp_servers)
    await manager.start()
    mcphub.set_active(manager)
    request.app.state.mcp = manager
    return manager.status()


def _skills_manager() -> SkillsManager:
    manager = skillhub.active_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="skills manager not active")
    return manager


@router.get("/skills")
def list_skills(request: Request) -> list[dict]:
    manager = skillhub.active_manager()
    return manager.list_skills() if manager is not None else []


@router.get("/skills/{name}")
def get_skill(request: Request, name: str) -> dict:
    try:
        content = _skills_manager().read(name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return {"name": name, "content": content}


class SkillContentRequest(BaseModel):
    content: str


@router.put("/skills/{name}")
def put_skill(request: Request, name: str, body: SkillContentRequest) -> dict:
    ws: Workspace = request.app.state.workspace
    manager = _skills_manager()
    try:
        previous = manager.read(name)
    except FileNotFoundError:
        previous = None
    try:
        manager.write(name, body.content)
    except SkillValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors) from None
    # The confirmation covered the content the user reviewed, not the name:
    # rewriting the body reopens the gate. The active manager shares
    # ws.config.skills, so the reset takes effect without a reload.
    confirmation_reset = False
    if previous is not None and previous != body.content:
        skill_config = ws.config.skills.get(name)
        if skill_config is not None and skill_config.confirmed:
            skill_config.confirmed = False
            save_config(ws.root, ws.config)
            confirmation_reset = True
    return {"saved": True, "confirmation_reset": confirmation_reset}


class SkillCreateRequest(BaseModel):
    name: str


@router.post("/skills", status_code=201)
def create_skill(request: Request, body: SkillCreateRequest) -> dict:
    try:
        _skills_manager().create(body.name)
    except SkillValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors) from None
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"created": body.name}


class SkillImportRequest(BaseModel):
    content: str


@router.post("/skills/import", status_code=201)
def import_skill(request: Request, body: SkillImportRequest) -> dict:
    """Create a skill from a full SKILL.md document, naming it from the
    frontmatter. The imported skill lands unconfirmed like any other: the
    settings panel's confirmation card still gates it into the agent."""
    try:
        name = _skills_manager().import_content(body.content)
    except SkillValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors) from None
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {"created": name}


@router.delete("/skills/{name}")
def delete_skill(request: Request, name: str) -> dict:
    try:
        _skills_manager().delete(name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return {"deleted": True}


_GLOSSARY_DOMAINS = {"video", "audio", "document", "comic", "general"}


def _glossary_store(request: Request) -> GlossaryStore:
    ws: Workspace = request.app.state.workspace
    return GlossaryStore(ws.root)


def _glossary_meta_dict(meta: GlossaryTableMeta) -> dict:
    return {
        "id": meta.id,
        "name": meta.name,
        "domain": meta.domain,
        "enabled": meta.enabled,
        "created_at": meta.created_at,
        "updated_at": meta.updated_at,
    }


def _require_glossary_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed:
        raise HTTPException(status_code=422, detail="glossary name is required")
    return trimmed


def _require_glossary_domain(domain: str) -> str:
    if domain not in _GLOSSARY_DOMAINS:
        raise HTTPException(status_code=422, detail=f"invalid domain: {domain}")
    return domain


def _glossary_not_found(glossary_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"glossary not found: {glossary_id}")


@router.get("/glossaries")
def list_glossaries(request: Request, domain: str | None = None) -> list[dict]:
    store = _glossary_store(request)
    rows: list[dict] = []
    for meta in store.list_tables(domain):
        row = _glossary_meta_dict(meta)
        row["entry_count"] = len(store.read_entries(meta.id))
        rows.append(row)
    return rows


class GlossaryCreateRequest(BaseModel):
    name: str
    domain: str


@router.post("/glossaries", status_code=201)
def create_glossary(request: Request, body: GlossaryCreateRequest) -> dict:
    name = _require_glossary_name(body.name)
    domain = _require_glossary_domain(body.domain)
    meta = _glossary_store(request).create_table(name, domain)
    return _glossary_meta_dict(meta)


class GlossaryImportRequest(BaseModel):
    name: str
    domain: str
    content: str
    format: str


@router.post("/glossaries/import", status_code=201)
def import_glossary(request: Request, body: GlossaryImportRequest) -> dict:
    name = _require_glossary_name(body.name)
    domain = _require_glossary_domain(body.domain)
    if body.format not in ("csv", "json"):
        raise HTTPException(status_code=422, detail=f"invalid format: {body.format}")
    store = _glossary_store(request)
    try:
        meta, skipped = store.import_table(name, domain, body.content, body.format)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    row = _glossary_meta_dict(meta)
    row["entry_count"] = len(store.read_entries(meta.id))
    row["skipped"] = skipped
    return row


@router.get("/glossaries/{glossary_id}")
def get_glossary(request: Request, glossary_id: str) -> dict:
    store = _glossary_store(request)
    try:
        meta = store.get_table(glossary_id)
        entries = store.read_entries(glossary_id)
    except KeyError:
        raise _glossary_not_found(glossary_id) from None
    row = _glossary_meta_dict(meta)
    row["entries"] = [asdict(entry) for entry in entries]
    return row


class GlossaryPatchRequest(BaseModel):
    name: str | None = None
    enabled: bool | None = None


@router.patch("/glossaries/{glossary_id}")
def patch_glossary(request: Request, glossary_id: str, body: GlossaryPatchRequest) -> dict:
    store = _glossary_store(request)
    try:
        if body.name is not None:
            store.rename_table(glossary_id, _require_glossary_name(body.name))
        if body.enabled is not None:
            store.set_enabled(glossary_id, body.enabled)
        meta = store.get_table(glossary_id)
    except KeyError:
        raise _glossary_not_found(glossary_id) from None
    return _glossary_meta_dict(meta)


@router.delete("/glossaries/{glossary_id}")
def delete_glossary(request: Request, glossary_id: str) -> dict:
    try:
        _glossary_store(request).delete_table(glossary_id)
    except KeyError:
        raise _glossary_not_found(glossary_id) from None
    return {"deleted": True}


class GlossaryEntryModel(BaseModel):
    source: str
    target: str
    notes: str = ""
    category: str = ""


class GlossaryEntriesRequest(BaseModel):
    entries: list[GlossaryEntryModel]


@router.put("/glossaries/{glossary_id}/entries")
def put_glossary_entries(
    request: Request, glossary_id: str, body: GlossaryEntriesRequest
) -> dict:
    entries = [
        GlossaryEntry(
            source=e.source.strip(),
            target=e.target.strip(),
            notes=e.notes.strip(),
            category=e.category.strip(),
        )
        for e in body.entries
        if e.source.strip() and e.target.strip()
    ]
    try:
        _glossary_store(request).write_entries(glossary_id, entries)
    except KeyError:
        raise _glossary_not_found(glossary_id) from None
    return {"saved": True, "count": len(entries)}


@router.get("/glossaries/{glossary_id}/export")
def export_glossary(request: Request, glossary_id: str, format: str = "csv") -> Response:
    if format not in ("csv", "json"):
        raise HTTPException(status_code=422, detail=f"invalid format: {format}")
    try:
        content = _glossary_store(request).export_table(glossary_id, format)
    except KeyError:
        raise _glossary_not_found(glossary_id) from None
    media_type = "application/json" if format == "json" else "text/csv"
    ext = "json" if format == "json" else "csv"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{glossary_id}.{ext}"'
        },
    )


@router.get("/proposals")
def list_proposals(request: Request, status: str | None = None) -> list[dict]:
    ws: Workspace = request.app.state.workspace
    return proposals.list_proposals(ws.root, status=status)


@router.post("/proposals/{proposal_id}/approve")
def approve_proposal(request: Request, proposal_id: str) -> dict:
    """Apply a pending proposal, then converge the running service on the
    new config exactly like put_config (skills manager included). The
    candidate config is pre-flighted through notifier construction BEFORE
    anything is applied, so approve cannot persist a config the service
    would fail to boot from. MCP servers are NOT reloaded here; the UI
    drives that through POST /mcp/reload as usual."""
    ws: Workspace = request.app.state.workspace
    try:
        candidate = proposals.candidate_config(ws.root, proposal_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"proposal not found: {proposal_id}"
        ) from None
    # ValidationError subclasses ValueError, so it must be caught first to
    # keep invalid merges (422) apart from non-pending proposals (409).
    except ValidationError as error:
        raise HTTPException(
            status_code=422, detail=error.errors(include_url=False)
        ) from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    try:
        notifier = Notifier.from_config(candidate)
    except NotifyError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    proposals.approve(ws.root, proposal_id)
    config = load_config(ws.root)
    _adopt_config(request.app, config, notifier)
    return config.model_dump()


@router.post("/proposals/{proposal_id}/reject")
def reject_proposal(request: Request, proposal_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    try:
        return proposals.reject(ws.root, proposal_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"proposal not found: {proposal_id}"
        ) from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.get("/profiles")
def list_profiles(request: Request) -> list[str]:
    ws: Workspace = request.app.state.workspace
    return sorted(path.stem for path in (ws.root / "profiles").glob("*.yaml"))


@router.get("/profiles/detailed")
def list_profiles_detailed(request: Request) -> list[dict]:
    """Profiles with their inferred task kind (video/document/comic), for the
    new-task type picker."""
    ws: Workspace = request.app.state.workspace
    from ..profiles import list_profiles_detailed as _detailed

    return _detailed(ws.root)


def _artifact_store(ws: Workspace, project: str, task_id: str) -> ArtifactStore:
    return ArtifactStore(ws.store.task_dir(project, task_id))


@router.get("/tasks/{project}/{task_id}/artifacts")
def list_artifacts(request: Request, project: str, task_id: str) -> list[dict]:
    ws: Workspace = request.app.state.workspace
    _load_task(ws, project, task_id)
    return _artifact_store(ws, project, task_id).list_artifacts()


@router.get("/tasks/{project}/{task_id}/artifacts/{name}")
def read_artifact(
    request: Request, project: str, task_id: str, name: str, version: str = "latest"
) -> dict:
    ws: Workspace = request.app.state.workspace
    _load_task(ws, project, task_id)
    store = _artifact_store(ws, project, task_id)
    try:
        if version == "latest":
            return store.read_latest_json(name)
        return store.read_named_json(f"{int(version):02d}-{name}")
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


class ArtifactSaveResult(BaseModel):
    file: str
    stages_reset: int


@router.put("/tasks/{project}/{task_id}/artifacts/{name}")
def save_artifact(
    request: Request, project: str, task_id: str, name: str, body: dict
) -> ArtifactSaveResult:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    if name == "translation.json":
        # Subtitle and document pipelines share the artifact name but not
        # the shape; dispatch on the payload's top-level key.
        if "segments" in body:
            try:
                validate_translation_payload(body)
            except ArtifactValidationError as error:
                raise HTTPException(status_code=422, detail=str(error)) from None
        elif "chunks" in body:
            try:
                DocTranslationDoc.model_validate(body)
            except ValidationError as error:
                raise HTTPException(status_code=422, detail=str(error)) from None
        else:
            raise HTTPException(
                status_code=422, detail="unrecognized translation payload"
            )
    elif name == "speakers.json":
        try:
            SpeakersDoc.model_validate(body)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None
    store = _artifact_store(ws, project, task_id)
    path = store.write_next_json(name, body)
    stages_reset = reset_stages_after_artifact(record, name)
    # Editing a finished task's artifact must let it run again. COMPLETED is a
    # terminal state the transition map won't leave and _RUNNABLE excludes, so
    # reopen to PENDING directly. This is an edit-driven reopen, not a runtime
    # transition — hence the direct assign rather than transition().
    if stages_reset > 0 and record.status == TaskStatus.COMPLETED:
        record.status = TaskStatus.PENDING
    ws.store.save(record)
    return ArtifactSaveResult(file=path.name, stages_reset=stages_reset)


@router.get("/styles")
def get_styles(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    path = ws.root / "config" / "styles.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@router.put("/styles")
def put_styles(request: Request, body: dict) -> dict:
    ws: Workspace = request.app.state.workspace
    path = ws.root / "config" / "styles.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return {"saved": True}


def _sync_once(app: FastAPI) -> SyncReport | None:
    """Run one sync pass; returns None when a sync is already in flight.

    A pulled core.yaml is reloaded into the running workspace right away
    (with the notifier reattached) so budget limits and channels from
    another machine take effect without a restart.
    """
    ws: Workspace = app.state.workspace
    target = create_target(ws.config.sync)
    lock: threading.Lock = app.state.sync_lock
    if not lock.acquire(blocking=False):
        return None
    try:
        report = SyncEngine(ws.root, target).run()
    finally:
        lock.release()
    if "config/core.yaml" in report.pulled + report.merged:
        config = load_config(ws.root)
        _adopt_config(app, config, Notifier.from_config(config))
    return report


@router.get("/sync/status")
def sync_status(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    state = load_state(ws.root)
    return {
        "enabled": ws.config.sync.enabled,
        "mode": ws.config.sync.mode,
        "syncing": request.app.state.sync_lock.locked(),
        "last_sync": state.get("last_sync"),
        "last_result": state.get("last_result"),
        "conflicts": load_conflicts(ws.root),
        "peers": list_peers(ws.root),
    }


@router.post("/sync/run")
def sync_run(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    if not ws.config.sync.enabled:
        raise HTTPException(status_code=400, detail="sync is not enabled")
    try:
        report = _sync_once(request.app)
    except SyncConfigError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    if report is None:
        raise HTTPException(status_code=409, detail="sync already running")
    return report.to_dict()


class SyncResolveRequest(BaseModel):
    file: str
    source: str
    choice: str


@router.post("/sync/resolve")
def sync_resolve(request: Request, body: SyncResolveRequest) -> dict:
    ws: Workspace = request.app.state.workspace
    if body.choice not in ("local", "remote"):
        raise HTTPException(status_code=422, detail="choice must be local or remote")
    if not resolve_conflict(ws.root, body.file, body.source, body.choice):
        raise HTTPException(
            status_code=404, detail=f"no conflict for {body.file}:{body.source}"
        )
    return {"resolved": True}


class RenderFrameRequest(BaseModel):
    style: dict
    text: str
    width: int = 1280
    height: int = 720
    background: str = "black"


@router.post("/tasks/{project}/{task_id}/render-frame")
def render_frame(
    request: Request, project: str, task_id: str, body: RenderFrameRequest
) -> Response:
    ws: Workspace = request.app.state.workspace
    _load_task(ws, project, task_id)
    if not ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg not available")
    style = SubtitleStyle(**body.style)
    with tempfile.TemporaryDirectory() as work:
        out = Path(work) / "frame.png"
        try:
            render_style_frame(
                style, body.text, out,
                width=body.width, height=body.height,
                background=body.background, work_dir=Path(work),
            )
        except MediaError as error:
            raise HTTPException(status_code=500, detail=str(error)) from None
        return Response(content=out.read_bytes(), media_type="image/png")


class AssistantMessageRequest(BaseModel):
    text: str
    # Present on the edit-and-resend path: truncate the active session at this
    # message index before running the turn.
    edit_index: int | None = None
    # Absolute paths of image files attached to this message.
    images: list[str] | None = None
    # UI language the message was sent from ("zh-TW" | "en" | "ja"); picks the
    # assistant's system prompt and thereby the reply language.
    lang: str | None = None


@router.post("/assistant/message")
def post_assistant_message(request: Request, body: AssistantMessageRequest) -> dict:
    ws: Workspace = request.app.state.workspace
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    try:
        result = run_assistant_message(
            ws,
            body.text,
            edit_index=body.edit_index,
            images=body.images,
            lang=body.lang or "zh-TW",
        )
    except AssistantUnavailable as error:
        # No usable LLM provider: 409 so the panel can guide the operator to
        # configuration rather than surfacing a generic server error.
        raise HTTPException(status_code=409, detail=str(error)) from None
    except AssistantLLMError as error:
        # Provider configured but the call failed (bad key, unknown model,
        # quota, network). 502 with the raw message so the panel classifies
        # it into readable wording instead of a generic 500.
        raise HTTPException(status_code=502, detail=str(error)) from None
    return {**result, "history": load_assistant_history(ws)}


# Pasted images arrive as bytes with no path of their own; the accepted mimes
# mirror the picker's extension filter so both attach routes take the same set.
_ATTACHMENT_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024


class AssistantAttachmentRequest(BaseModel):
    mime: str
    data_base64: str


@router.post("/assistant/attachments", status_code=201)
def post_assistant_attachment(
    request: Request, body: AssistantAttachmentRequest
) -> dict:
    """Save a pasted image into the workspace and return its absolute path,
    so clipboard images ride the same `images` channel as picker-chosen
    files. Files land under assistant/attachments/ and are never cleaned up
    automatically: history messages keep referencing them."""
    ws: Workspace = request.app.state.workspace
    ext = _ATTACHMENT_MIME_EXT.get(body.mime)
    if ext is None:
        raise HTTPException(
            status_code=422, detail=f"unsupported image mime: {body.mime}"
        )
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=422, detail="data_base64 is not valid base64"
        ) from None
    if not data:
        raise HTTPException(status_code=422, detail="image is empty")
    if len(data) > ATTACHMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="image exceeds 20 MB")
    directory = ws.root / "assistant" / "attachments"
    directory.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + f".{ext}"
    path = directory / name
    path.write_bytes(data)
    return {"path": str(path)}


@router.get("/assistant/history")
def get_assistant_history(request: Request) -> list[dict]:
    ws: Workspace = request.app.state.workspace
    return load_assistant_history(ws)


@router.post("/assistant/clear")
def post_assistant_clear(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    clear_assistant_history(ws)
    return {"cleared": True}


@router.get("/assistant/sessions")
def list_assistant_sessions(request: Request) -> list[dict]:
    ws: Workspace = request.app.state.workspace
    from ..agents import assistant_store

    return assistant_store.list_sessions(ws)


@router.post("/assistant/sessions", status_code=201)
def create_assistant_session(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    from ..agents import assistant_store

    return {"id": assistant_store.create_session(ws)}


@router.get("/assistant/sessions/{session_id}")
def get_assistant_session(request: Request, session_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    from ..agents import assistant_store

    try:
        return assistant_store.get_session(ws, session_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"session not found: {session_id}"
        ) from None


@router.post("/assistant/sessions/{session_id}/activate")
def activate_assistant_session(request: Request, session_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    from ..agents import assistant_store

    try:
        assistant_store.activate_session(ws, session_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"session not found: {session_id}"
        ) from None
    return {"active": session_id}


class SessionArchiveRequest(BaseModel):
    archived: bool


@router.patch("/assistant/sessions/{session_id}")
def patch_assistant_session(
    request: Request, session_id: str, body: SessionArchiveRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    from ..agents import assistant_store

    try:
        assistant_store.set_archived(ws, session_id, body.archived)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"session not found: {session_id}"
        ) from None
    return {"archived": body.archived}


@router.delete("/assistant/sessions/{session_id}")
def delete_assistant_session(request: Request, session_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    from ..agents import assistant_store

    try:
        assistant_store.delete_session(ws, session_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"session not found: {session_id}"
        ) from None
    return {"deleted": True}


def _log_bot_exit(task: "asyncio.Task") -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logging.getLogger(__name__).error("discord bot exited: %s", error)


def create_app(data_root: Path | None = None) -> FastAPI:
    workspace = Workspace.open(data_root)
    worker = TaskWorker(workspace)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        mcp_manager = MCPManager(workspace.config.mcp_servers)
        await mcp_manager.start()
        mcphub.set_active(mcp_manager)
        app.state.mcp = mcp_manager
        skillhub.set_active(SkillsManager(workspace.root, workspace.config.skills))
        bot_task: asyncio.Task | None = None
        bot_config = workspace.config.discord_bot
        if bot_config.enabled:
            if bot_config.resolve_token():
                # Imported lazily so serving without the bot never pays the
                # discord.py import cost.
                from ..bot import runner as bot_runner

                bot_task = asyncio.create_task(bot_runner.run_bot(app, bot_config))
                bot_task.add_done_callback(_log_bot_exit)
            else:
                logging.getLogger(__name__).warning(
                    "discord bot enabled but no token configured; not starting"
                )
        scheduler: SyncScheduler | None = None
        sync_config = workspace.config.sync
        if sync_config.enabled and sync_config.auto_interval_minutes > 0:

            def scheduled_sync() -> None:
                report = _sync_once(app)
                if report is not None and not report.ok:
                    logging.getLogger(__name__).warning(
                        "scheduled sync failed: %s", report.error
                    )

            scheduler = SyncScheduler(
                sync_config.auto_interval_minutes * 60, scheduled_sync
            )
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.stop()
        if bot_task is not None:
            bot_task.cancel()
            with suppress(asyncio.CancelledError):
                await bot_task
        mcphub.set_active(None)
        skillhub.set_active(None)
        await app.state.mcp.stop()
        worker.stop()

    app = FastAPI(
        title="traduko core", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    # Browser-based clients (the Tauri desktop shell's webview) fetch from a
    # non-http origin such as tauri://localhost. The service binds to
    # 127.0.0.1 and every data endpoint requires the bearer token, so the
    # token is the security boundary; CORS only unblocks the webview.
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.state.workspace = workspace
    app.state.worker = worker
    app.state.token = load_or_create_token(workspace.root)
    app.state.sync_lock = threading.Lock()
    app.state.asr = AsrManager()
    app.state.macos_asr = MacosAsrManager(workspace.root)
    app.state.dubbing = DubbingManager(
        workspace.root, python_override=workspace.config.dubbing.python
    )
    app.state.pdf = PdfManager(
        workspace.root, python_override=workspace.config.pdf.python
    )

    broadcaster = WsBroadcaster()
    broadcaster.attach(workspace.bus)
    app.state.broadcaster = broadcaster

    setup_system_log(workspace.root)
    EventLogger(workspace.root).attach(workspace.bus)
    app.state.detach_notifier = Notifier.from_config(workspace.config).attach(
        workspace.bus
    )
    logging.getLogger(__name__).info("service initialized at %s", workspace.root)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(ws_router)
    return app
