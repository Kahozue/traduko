from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .eventlog import EventLogger
from .events import Event
from .executor import PipelineExecutor
from .glossary import GlossaryStore, resolve_effective_glossary
from .models import StageRecord, StageStatus, TaskGlossary, TaskStatus
from .notify import Notifier
from .paths import ENV_DATA_ROOT
from .preflight import PreflightReport, run_preflight
from .profiles import load_profile, stage_records_from
from .workspace import Workspace

app = typer.Typer(no_args_is_help=True)
task_app = typer.Typer(no_args_is_help=True)
app.add_typer(task_app, name="task")
glossary_app = typer.Typer(no_args_is_help=True)
app.add_typer(glossary_app, name="glossary")


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


def _print_report(report: PreflightReport) -> None:
    for check in report.checks:
        typer.echo(f"[{check.level}] {check.name}: {check.message}")


@task_app.command("preflight")
def task_preflight(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    ws: Workspace = ctx.obj
    record = ws.store.load(project or ws.config.default_project, task_id)
    report = run_preflight(record, ws.root)
    _print_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


@task_app.command("run")
def task_run(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    project: Optional[str] = typer.Option(None, "--project"),
    skip_preflight: bool = typer.Option(
        False, "--skip-preflight", help="Run without preflight checks."
    ),
) -> None:
    ws: Workspace = ctx.obj

    def print_event(event: Event) -> None:
        typer.echo(f"[{event.type}] {json.dumps(event.data, ensure_ascii=False)}")

    ws.bus.subscribe(print_event)
    EventLogger(ws.root).attach(ws.bus)
    Notifier.from_config(ws.config).attach(ws.bus)
    record = ws.store.load(project or ws.config.default_project, task_id)
    if not skip_preflight:
        report = run_preflight(record, ws.root)
        if not report.ok:
            _print_report(report)
            typer.echo("preflight failed (fix the issues or use --skip-preflight)")
            raise typer.Exit(code=1)
    result = PipelineExecutor(ws.store, ws.bus, ws.root).run(record)
    typer.echo(result.status.value)


@task_app.command("rerun")
def task_rerun(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    project: Optional[str] = typer.Option(None, "--project"),
    skip_preflight: bool = typer.Option(
        False, "--skip-preflight", help="Rerun without preflight checks."
    ),
) -> None:
    """Rerun a completed task from scratch (all stages run again)."""
    ws: Workspace = ctx.obj

    def print_event(event: Event) -> None:
        typer.echo(f"[{event.type}] {json.dumps(event.data, ensure_ascii=False)}")

    ws.bus.subscribe(print_event)
    EventLogger(ws.root).attach(ws.bus)
    Notifier.from_config(ws.config).attach(ws.bus)
    record = ws.store.load(project or ws.config.default_project, task_id)
    if record.status is not TaskStatus.COMPLETED:
        typer.echo(f"cannot rerun task in status {record.status.value}")
        raise typer.Exit(code=1)
    # Preflight before the reset: a failing rerun leaves the completed task as
    # it was, so the operator can restore the input or retry with skip.
    if not skip_preflight:
        report = run_preflight(record, ws.root)
        if not report.ok:
            _print_report(report)
            typer.echo("preflight failed (fix the issues or use --skip-preflight)")
            raise typer.Exit(code=1)
    ws.store.reset_for_rerun(record)
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


@task_app.command("glossary")
def task_glossary(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    project: Optional[str] = typer.Option(None, "--project"),
) -> None:
    """Show the effective glossary config and merged entry count for a task."""
    ws: Workspace = ctx.obj
    proj = project or ws.config.default_project
    record = ws.store.load(proj, task_id)
    typer.echo(f"global_ids: {record.glossary.global_ids}")
    typer.echo(f"use_task: {record.glossary.use_task}")
    typer.echo(f"asr_mode: {record.glossary.asr_mode}")
    entries = resolve_effective_glossary(ws.root, record)
    typer.echo(f"merged entries: {len(entries)}")


@task_app.command("glossary-set")
def task_glossary_set(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    project: Optional[str] = typer.Option(None, "--project"),
    global_ids: Optional[str] = typer.Option(
        None, "--global-ids", help="Comma-separated global glossary table ids."
    ),
    use_task: Optional[bool] = typer.Option(None, "--use-task/--no-use-task"),
    asr_mode: Optional[str] = typer.Option(
        None, "--asr-mode", help="auto, force, or off"
    ),
) -> None:
    """Write the task glossary config."""
    ws: Workspace = ctx.obj
    proj = project or ws.config.default_project
    record = ws.store.load(proj, task_id)
    ids = record.glossary.global_ids
    if global_ids is not None:
        ids = [x.strip() for x in global_ids.split(",") if x.strip()]
        # Validate ids exist
        store = GlossaryStore(ws.root)
        known = {m.id for m in store.list_tables()}
        unknown = [i for i in ids if i not in known]
        if unknown:
            typer.echo(f"unknown glossary id: {', '.join(unknown)}")
            raise typer.Exit(code=1)
    mode = record.glossary.asr_mode
    if asr_mode is not None:
        if asr_mode not in ("auto", "force", "off"):
            typer.echo(f"invalid asr_mode: {asr_mode}")
            raise typer.Exit(code=1)
        mode = asr_mode
    record.glossary = TaskGlossary(
        global_ids=ids,
        use_task=use_task if use_task is not None else record.glossary.use_task,
        asr_mode=mode,
    )
    ws.store.save(record)
    typer.echo(f"global_ids: {record.glossary.global_ids}")
    typer.echo(f"use_task: {record.glossary.use_task}")
    typer.echo(f"asr_mode: {record.glossary.asr_mode}")


@task_app.command("glossary-reapply")
def task_glossary_reapply(
    ctx: typer.Context,
    task_id: str = typer.Argument(...),
    mode: str = typer.Option(..., "--mode", help="asr, proofread, or translate"),
    project: Optional[str] = typer.Option(None, "--project"),
    skip_preflight: bool = typer.Option(False, "--skip-preflight"),
) -> None:
    """Reset stages and rerun the pipeline from the specified point."""
    ws: Workspace = ctx.obj
    proj = project or ws.config.default_project
    record = ws.store.load(proj, task_id)

    if mode not in ("asr", "proofread", "translate"):
        typer.echo(f"invalid mode: {mode}")
        raise typer.Exit(code=1)

    reset_from_type: str | None = None

    if mode == "asr":
        asr_index = next(
            (i for i, s in enumerate(record.stages) if s.type == "asr"), None
        )
        if asr_index is None:
            typer.echo("no asr stage to reapply")
            raise typer.Exit(code=1)
        from .tasks import ensure_glossary_proofread_stage
        ensure_glossary_proofread_stage(record, ws.config)
        reset_from_type = "asr"

    elif mode == "proofread":
        asr_index = next(
            (i for i, s in enumerate(record.stages) if s.type == "asr"), None
        )
        if asr_index is None:
            typer.echo("no asr stage to reapply")
            raise typer.Exit(code=1)
        gp = next(
            (s for s in record.stages if s.type == "glossary_proofread"), None
        )
        if gp is None:
            record.stages.insert(asr_index + 1, StageRecord(type="glossary_proofread"))
        reset_from_type = "glossary_proofread"

    elif mode == "translate":
        trans_index = next(
            (i for i, s in enumerate(record.stages)
             if s.type in {"translate", "translate_chunks"}),
            None,
        )
        if trans_index is None:
            typer.echo("no translate stage to reapply")
            raise typer.Exit(code=1)
        reset_from_type = record.stages[trans_index].type

    assert reset_from_type is not None
    reset_index = next(
        i for i, s in enumerate(record.stages) if s.type == reset_from_type
    )
    for stage in record.stages[reset_index:]:
        stage.status = StageStatus.PENDING
        stage.error = None
    record.status = TaskStatus.PENDING
    ws.store.save(record)

    if not skip_preflight:
        report = run_preflight(record, ws.root)
        if not report.ok:
            _print_report(report)
            typer.echo("preflight failed (fix or use --skip-preflight)")
            raise typer.Exit(code=1)

    def print_event(event: Event) -> None:
        typer.echo(f"[{event.type}] {json.dumps(event.data, ensure_ascii=False)}")

    ws.bus.subscribe(print_event)
    EventLogger(ws.root).attach(ws.bus)
    Notifier.from_config(ws.config).attach(ws.bus)
    result = PipelineExecutor(ws.store, ws.bus, ws.root).run(record)
    typer.echo(result.status.value)


@app.command("serve")
def serve(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8686, "--port", help="Bind port."),
    parent_pid: int | None = typer.Option(
        None,
        "--parent-pid",
        envvar="TRADUKO_PARENT_PID",
        help="Exit when this process dies (set by the desktop app).",
    ),
) -> None:
    import uvicorn

    from .service.app import create_app
    from .service.parentwatch import ParentWatchdog

    ws: Workspace = ctx.obj
    watchdog = ParentWatchdog(parent_pid) if parent_pid else None
    if watchdog:
        watchdog.start()
    try:
        uvicorn.run(create_app(ws.root), host=host, port=port, log_level="info")
    finally:
        if watchdog:
            watchdog.stop()


@app.command("sync")
def sync(ctx: typer.Context) -> None:
    """Run one cloud sync pass against the configured target."""
    from .sync.engine import SyncConfigError, SyncEngine, create_target

    ws: Workspace = ctx.obj
    if not ws.config.sync.enabled:
        typer.echo("sync is not enabled (see config/core.yaml)")
        raise typer.Exit(code=1)
    try:
        target = create_target(ws.config.sync)
    except SyncConfigError as error:
        typer.echo(str(error))
        raise typer.Exit(code=1) from None
    report = SyncEngine(ws.root, target).run()
    typer.echo(f"pushed: {len(report.pushed)}")
    typer.echo(f"pulled: {len(report.pulled)}")
    typer.echo(f"merged: {len(report.merged)}")
    typer.echo(f"conflicts: {report.conflicts}")
    if report.conflicts:
        typer.echo("resolve glossary conflicts in the desktop app settings page")
    if not report.ok:
        typer.echo(f"sync failed: {report.error}")
        raise typer.Exit(code=1)


def _glossary_store(ctx: typer.Context) -> GlossaryStore:
    ws: Workspace = ctx.obj
    return GlossaryStore(ws.root)


@glossary_app.command("list")
def glossary_list(
    ctx: typer.Context,
    domain: Optional[str] = typer.Option(None, "--domain", help="Filter by domain."),
) -> None:
    store = _glossary_store(ctx)
    for meta in store.list_tables(domain):
        count = len(store.read_entries(meta.id))
        state = "enabled" if meta.enabled else "disabled"
        typer.echo(f"{meta.id}  {meta.name}  ({meta.domain})  {state}  {count} entries")


@glossary_app.command("show")
def glossary_show(
    ctx: typer.Context, table_id: str = typer.Argument(..., help="Glossary table id.")
) -> None:
    store = _glossary_store(ctx)
    try:
        entries = store.read_entries(table_id)
    except KeyError:
        typer.echo(f"glossary not found: {table_id}")
        raise typer.Exit(code=1) from None
    for entry in entries:
        line = f"{entry.source} -> {entry.target}"
        if entry.notes:
            line += f" ({entry.notes})"
        if entry.category:
            line += f" #{entry.category}"
        typer.echo(line)


@glossary_app.command("import")
def glossary_import(
    ctx: typer.Context,
    file: Path = typer.Argument(..., help="CSV or JSON glossary file."),
    domain: str = typer.Option("general", "--domain", help="Table domain."),
    name: Optional[str] = typer.Option(None, "--name", help="Table name."),
) -> None:
    if not file.exists():
        raise typer.BadParameter(f"file not found: {file}")
    fmt = "json" if file.suffix.lower() == ".json" else "csv"
    store = _glossary_store(ctx)
    try:
        meta = store.import_table(
            name or file.stem, domain, file.read_text(encoding="utf-8"), fmt
        )
    except ValueError as error:
        typer.echo(f"import failed: {error}")
        raise typer.Exit(code=1) from None
    typer.echo(meta.id)


@glossary_app.command("export")
def glossary_export(
    ctx: typer.Context,
    table_id: str = typer.Argument(..., help="Glossary table id."),
    format: str = typer.Option("csv", "--format", help="csv or json."),
    out: Optional[Path] = typer.Option(None, "--out", help="Write to file instead of stdout."),
) -> None:
    store = _glossary_store(ctx)
    try:
        content = store.export_table(table_id, format)
    except KeyError:
        typer.echo(f"glossary not found: {table_id}")
        raise typer.Exit(code=1) from None
    if out is not None:
        out.write_text(content, encoding="utf-8")
        typer.echo(str(out))
    else:
        typer.echo(content)


def _set_glossary_enabled(ctx: typer.Context, table_id: str, enabled: bool) -> None:
    store = _glossary_store(ctx)
    try:
        store.set_enabled(table_id, enabled)
    except KeyError:
        typer.echo(f"glossary not found: {table_id}")
        raise typer.Exit(code=1) from None
    typer.echo(f"{table_id} {'enabled' if enabled else 'disabled'}")


@glossary_app.command("enable")
def glossary_enable(
    ctx: typer.Context, table_id: str = typer.Argument(..., help="Glossary table id.")
) -> None:
    _set_glossary_enabled(ctx, table_id, True)


@glossary_app.command("disable")
def glossary_disable(
    ctx: typer.Context, table_id: str = typer.Argument(..., help="Glossary table id.")
) -> None:
    _set_glossary_enabled(ctx, table_id, False)
