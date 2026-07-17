"""FastAPI service: the resident core every client talks to (design doc section 2).

Binds to 127.0.0.1 by default; GUI, CLI, Discord bot and webhooks are all
clients of this API, so each feature is implemented exactly once. Auth is
a bearer token generated on first start (config/api-token in the data
root); /health is the only unauthenticated route. One Workspace lives for
the whole app lifetime; handlers reach it through request.app.state.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import tempfile
import threading
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

import yaml

from .. import asrsetup
from ..asrsetup import AsrManager
from ..agents.assistant import (
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
from ..eventlog import EventLogger
from ..executor import reset_stages_after_artifact
from ..events import Event
from ..media import MediaError, ffmpeg_available
from .. import mcphub
from ..mcphub import MCPManager
from ..models import InvalidTransition, TaskRecord, TaskStatus, transition
from ..notify import Notifier, NotifyError, create_channel
from ..preflight import run_preflight
from ..profiles import load_profile, stage_records_from
from .. import proposals, skillhub
from ..skillhub import SkillsManager, SkillValidationError
from ..styles import SubtitleStyle
from ..styles_render import render_style_frame
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


@router.get("/budget")
def get_budget(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    meter = BudgetMeter(ws.root, ws.bus, ws.config)
    # Lifetime per-task spend across all ledgers, with names joined from the
    # index; tasks whose records are gone still show up under their raw id.
    spent: dict[str, dict] = {}
    for path in sorted((ws.root / "budget").glob("ledger-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            task_id = row.get("task_id", "")
            entry = spent.setdefault(
                task_id,
                {"task_id": task_id, "project": row.get("project", ""), "usd": 0.0},
            )
            entry["usd"] += float(row.get("cost_usd", 0.0))
    names = {row["id"]: row.get("name") for row in ws.index.list()}
    tasks = [
        {**entry, "name": names.get(entry["task_id"]), "usd": round(entry["usd"], 6)}
        for entry in spent.values()
    ]
    tasks.sort(key=lambda entry: entry["usd"], reverse=True)
    return {
        "month_usd": meter.month_usage_usd(),
        "task_usd_limit": ws.config.budget.task_usd_limit,
        "monthly_usd_limit": ws.config.budget.monthly_usd_limit,
        "tasks": tasks[:50],
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
    input_path: str
    profile: str
    project: str | None = None
    name: str | None = None


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
    input_path = Path(body.input_path)
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"input not found: {input_path}")
    try:
        profile = load_profile(ws.root, body.profile)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"profile not found: {body.profile}"
        ) from None
    record = ws.store.create(
        project=body.project or ws.config.default_project,
        input_path=str(input_path.resolve()),
        profile_name=body.profile,
        stages=stage_records_from(profile),
        name=body.name,
    )
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


@router.patch("/tasks/{project}/{task_id}")
def update_task(
    request: Request, project: str, task_id: str, body: TaskUpdateRequest
) -> dict:
    ws: Workspace = request.app.state.workspace
    record = _load_task(ws, project, task_id)
    if body.name is None and body.project is None:
        raise HTTPException(status_code=422, detail="name or project required")
    name_changed = False
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="name must not be empty")
        record.name = name
        name_changed = True
    if body.project is not None:
        new_project = body.project.strip()
        if not new_project:
            raise HTTPException(status_code=422, detail="project must not be empty")
        if new_project != record.project:
            worker: TaskWorker = request.app.state.worker
            if worker.is_active(project, task_id):
                raise HTTPException(status_code=409, detail="task is queued or running")
            record = ws.store.move(record, new_project)
        elif name_changed:
            ws.store.save(record)
    elif name_changed:
        ws.store.save(record)
    return record.model_dump()


@router.delete("/tasks/{project}/{task_id}")
def delete_task(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    _load_task(ws, project, task_id)
    worker: TaskWorker = request.app.state.worker
    if worker.is_active(project, task_id):
        raise HTTPException(status_code=409, detail="task is queued or running")
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


@router.post("/tasks/{project}/{task_id}/run", status_code=202)
def run_task(
    request: Request, project: str, task_id: str, body: RunRequest | None = None
) -> dict:
    ws: Workspace = request.app.state.workspace
    worker: TaskWorker = request.app.state.worker
    record = _load_task(ws, project, task_id)
    if record.status not in _RUNNABLE:
        raise HTTPException(
            status_code=409,
            detail=f"cannot run task in status {record.status.value}",
        )
    if not (body and body.skip_preflight):
        report = run_preflight(record, ws.root)
        if not report.ok:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "preflight failed",
                    "checks": [asdict(check) for check in report.failures()],
                },
            )
    if not worker.enqueue(project, task_id):
        raise HTTPException(status_code=409, detail="task already queued or running")
    return {"queued": True}


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


class AsrModelRequest(BaseModel):
    model: str = "small"


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
def asr_test(request: Request, body: AsrModelRequest | None = None) -> dict:
    manager: AsrManager = request.app.state.asr
    model = (body or AsrModelRequest()).model
    status = manager.status(model)
    if not status["package"]:
        raise HTTPException(status_code=409, detail="asr engine is not available")
    if not status["cached"]:
        raise HTTPException(status_code=409, detail="model is not downloaded")
    return manager.test(model)


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


@router.delete("/skills/{name}")
def delete_skill(request: Request, name: str) -> dict:
    try:
        _skills_manager().delete(name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return {"deleted": True}


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


@router.post("/assistant/message")
def post_assistant_message(request: Request, body: AssistantMessageRequest) -> dict:
    ws: Workspace = request.app.state.workspace
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")
    try:
        result = run_assistant_message(ws, body.text)
    except AssistantUnavailable as error:
        # No usable LLM provider: 409 so the panel can guide the operator to
        # configuration rather than surfacing a generic server error.
        raise HTTPException(status_code=409, detail=str(error)) from None
    return {**result, "history": load_assistant_history(ws)}


@router.get("/assistant/history")
def get_assistant_history(request: Request) -> list[dict]:
    ws: Workspace = request.app.state.workspace
    return load_assistant_history(ws)


@router.post("/assistant/clear")
def post_assistant_clear(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    clear_assistant_history(ws)
    return {"cleared": True}


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
