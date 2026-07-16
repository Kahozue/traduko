"""FastAPI service: the resident core every client talks to (design doc section 2).

Binds to 127.0.0.1 by default; GUI, CLI, Discord bot and webhooks are all
clients of this API, so each feature is implemented exactly once. Auth is
a bearer token generated on first start (config/api-token in the data
root); /health is the only unauthenticated route. One Workspace lives for
the whole app lifetime; handlers reach it through request.app.state.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from ..budget import BudgetMeter
from ..workspace import Workspace
from .auth import load_or_create_token


def require_token(request: Request) -> None:
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {request.app.state.token}"
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid or missing token")


router = APIRouter(dependencies=[Depends(require_token)])


@router.get("/budget")
def get_budget(request: Request) -> dict:
    ws: Workspace = request.app.state.workspace
    meter = BudgetMeter(ws.root, ws.bus, ws.config)
    return {
        "month_usd": meter.month_usage_usd(),
        "task_usd_limit": ws.config.budget.task_usd_limit,
        "monthly_usd_limit": ws.config.budget.monthly_usd_limit,
    }


def create_app(data_root: Path | None = None) -> FastAPI:
    workspace = Workspace.open(data_root)
    app = FastAPI(title="traduko core", docs_url=None, redoc_url=None)
    app.state.workspace = workspace
    app.state.token = load_or_create_token(workspace.root)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(router)
    return app
