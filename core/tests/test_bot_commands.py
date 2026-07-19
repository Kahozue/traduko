import asyncio
from pathlib import Path

from traduko.bot import commands
from traduko.bot.api import CoreApi
from traduko.models import StageRecord, StageStatus, TaskStatus
from traduko.service.app import create_app


def make_api(tmp_path: Path):
    app = create_app(tmp_path)
    return app, CoreApi.for_app(app)


def make_task(app, tmp_path: Path, name: str | None = None, with_input: bool = True):
    input_path = tmp_path / "in.srt"
    if with_input:
        input_path.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
        )
    return app.state.workspace.store.create(
        project="p",
        input_path=str(input_path),
        profile_name="x",
        stages=[StageRecord(type="noop")],
        name=name,
    )


def make_completed_task(app, tmp_path: Path, name: str | None = None):
    record = make_task(app, tmp_path, name=name)
    record.status = TaskStatus.COMPLETED
    for stage in record.stages:
        stage.status = StageStatus.COMPLETED
    app.state.workspace.store.save(record)
    return record


def run(coro):
    return asyncio.run(coro)


def test_authorization_is_string_compared() -> None:
    assert commands.is_authorized(42, ["42"]) is True
    assert commands.is_authorized(42, ["7"]) is False
    assert commands.is_authorized(42, []) is False


def test_status_lists_and_details(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        assert await commands.status_command(api) == "目前沒有任何任務。"
        record = make_task(app, tmp_path, name="ep01")
        listing = await commands.status_command(api)
        assert "ep01" in listing and "等待中" in listing
        detail = await commands.status_command(api, record.id)
        assert "空階段" in detail
        assert "找不到任務" in await commands.status_command(api, "nope")
        await api.aclose()

    run(scenario())


def test_resume_queues_task_and_reports_preflight_failures(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        ok = make_task(app, tmp_path)
        reply = await commands.resume_command(api, ok.id)
        assert "排入執行佇列" in reply

        broken = make_task(app, tmp_path, with_input=False)
        (tmp_path / "in.srt").unlink()
        reply = await commands.resume_command(api, broken.id)
        assert "預檢未通過" in reply
        await api.aclose()

    run(scenario())


def test_rerun_queues_completed_and_reports_bad_states(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        assert "找不到任務" in await commands.rerun_command(api, "nope")

        pending = make_task(app, tmp_path)
        reply = await commands.rerun_command(api, pending.id)
        assert "無法執行" in reply

        done = make_completed_task(app, tmp_path)
        reply = await commands.rerun_command(api, done.id)
        assert "排入重新執行佇列" in reply
        await api.aclose()

    run(scenario())


def test_pause_and_cancel_replies(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        record = make_task(app, tmp_path)
        reply = await commands.pause_command(api, record.id)
        assert "無法暫停" in reply  # worker is not running in this test app
        reply = await commands.cancel_command(api, record.id)
        assert "已取消" in reply
        assert "找不到任務" in await commands.pause_command(api, "nope")
        await api.aclose()

    run(scenario())


def test_budget_show_and_update(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        reply = await commands.budget_command(api)
        assert "未設上限" in reply
        reply = await commands.budget_command(api, task_limit="5", monthly_limit="off")
        assert "5.00 USD" in reply and "每月上限：未設上限" in reply
        reply = await commands.budget_command(api, task_limit="abc")
        assert "不小於 0" in reply
        await api.aclose()

    run(scenario())
