"""FastAPI service: the resident core every client talks to (design doc section 2).

Binds to 127.0.0.1 by default; GUI, CLI, Discord bot and webhooks are all
clients of this API, so each feature is implemented exactly once. Auth is
a bearer token generated on first start (config/api-token in the data
root); /health is the only unauthenticated route. One Workspace lives for
the whole app lifetime; handlers reach it through request.app.state.
"""
from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
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
from pydantic import BaseModel

from ..budget import BudgetMeter
from ..events import Event
from ..models import InvalidTransition, TaskRecord, TaskStatus, transition
from ..preflight import run_preflight
from ..profiles import load_profile, stage_records_from
from ..workspace import Workspace
from .auth import load_or_create_token
from .broadcast import WsBroadcaster
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
    return {
        "month_usd": meter.month_usage_usd(),
        "task_usd_limit": ws.config.budget.task_usd_limit,
        "monthly_usd_limit": ws.config.budget.monthly_usd_limit,
    }


class TaskCreateRequest(BaseModel):
    input_path: str
    profile: str
    project: str | None = None


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
    )
    return record.model_dump()


@router.get("/tasks/{project}/{task_id}")
def show_task(request: Request, project: str, task_id: str) -> dict:
    ws: Workspace = request.app.state.workspace
    return _load_task(ws, project, task_id).model_dump()


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


@router.get("/profiles")
def list_profiles(request: Request) -> list[str]:
    ws: Workspace = request.app.state.workspace
    return sorted(path.stem for path in (ws.root / "profiles").glob("*.yaml"))


def create_app(data_root: Path | None = None) -> FastAPI:
    workspace = Workspace.open(data_root)
    worker = TaskWorker(workspace)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        worker.start()
        yield
        worker.stop()

    app = FastAPI(
        title="traduko core", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    app.state.workspace = workspace
    app.state.worker = worker
    app.state.token = load_or_create_token(workspace.root)

    broadcaster = WsBroadcaster()
    broadcaster.attach(workspace.bus)
    app.state.broadcaster = broadcaster

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(ws_router)
    return app
