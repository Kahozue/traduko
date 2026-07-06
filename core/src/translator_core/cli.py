from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .events import Event
from .executor import PipelineExecutor
from .paths import ENV_DATA_ROOT
from .profiles import load_profile, stage_records_from
from .workspace import Workspace

app = typer.Typer(no_args_is_help=True)
task_app = typer.Typer(no_args_is_help=True)
app.add_typer(task_app, name="task")


@app.callback()
def main(
    ctx: typer.Context,
    data_root: Optional[Path] = typer.Option(
        None, "--data-root", envvar=ENV_DATA_ROOT, help="Data root directory."
    ),
) -> None:
    ctx.obj = Workspace.open(data_root)


@task_app.command("create")
def task_create(
    ctx: typer.Context,
    input_path: Path = typer.Argument(..., help="Input media or subtitle file."),
    profile: str = typer.Option(..., "--profile", help="Profile name."),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    ws: Workspace = ctx.obj
    if not input_path.exists():
        raise typer.BadParameter(f"input not found: {input_path}")
    loaded = load_profile(ws.root, profile)
    record = ws.store.create(
        project=project or ws.config.default_project,
        input_path=str(input_path.resolve()),
        profile_name=profile,
        stages=stage_records_from(loaded),
    )
    typer.echo(record.id)


@task_app.command("run")
def task_run(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    ws: Workspace = ctx.obj

    def print_event(event: Event) -> None:
        typer.echo(f"[{event.type}] {json.dumps(event.data, ensure_ascii=False)}")

    ws.bus.subscribe(print_event)
    record = ws.store.load(project or ws.config.default_project, task_id)
    result = PipelineExecutor(ws.store, ws.bus, ws.root).run(record)
    typer.echo(result.status.value)


@task_app.command("list")
def task_list(
    ctx: typer.Context,
    project: Optional[str] = typer.Option(None, "--project"),
    status: Optional[str] = typer.Option(None, "--status"),
) -> None:
    ws: Workspace = ctx.obj
    for row in ws.index.list(project=project, status=status):
        typer.echo(
            f"{row['id']}  {row['project']}  {row['status']}  {row['profile']}"
        )


@task_app.command("show")
def task_show(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    ws: Workspace = ctx.obj
    record = ws.store.load(project or ws.config.default_project, task_id)
    typer.echo(record.model_dump_json(indent=2))
