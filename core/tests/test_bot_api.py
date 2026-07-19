import asyncio
from pathlib import Path

import pytest

from traduko.bot.api import CoreApi, CoreApiError
from traduko.models import StageRecord, StageStatus, TaskStatus
from traduko.service.app import create_app


def make_api(tmp_path: Path):
    app = create_app(tmp_path)
    return app, CoreApi.for_app(app)


def test_list_find_and_get_task(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        record = app.state.workspace.store.create(
            project="p",
            input_path="unused",
            profile_name="x",
            stages=[StageRecord(type="noop")],
            name="named",
        )
        rows = await api.list_tasks()
        assert [row["id"] for row in rows] == [record.id]
        found = await api.find_task(record.id)
        assert found is not None and found["project"] == "p"
        assert await api.find_task("nope") is None
        full = await api.get_task("p", record.id)
        assert full["name"] == "named"
        await api.aclose()

    asyncio.run(scenario())


def test_error_carries_status_and_detail(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        with pytest.raises(CoreApiError) as info:
            await api.get_task("p", "missing")
        assert info.value.status_code == 404
        assert "missing" in str(info.value.detail)
        await api.aclose()

    asyncio.run(scenario())


def test_rerun_task_hits_rerun_endpoint(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        input_path = tmp_path / "in.srt"
        input_path.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
        )
        record = app.state.workspace.store.create(
            project="p",
            input_path=str(input_path),
            profile_name="x",
            stages=[StageRecord(type="noop")],
        )
        # Mark completed: only the rerun endpoint accepts a COMPLETED task, so a
        # queued reply proves rerun_task hit /rerun and not /run.
        record.status = TaskStatus.COMPLETED
        for stage in record.stages:
            stage.status = StageStatus.COMPLETED
        app.state.workspace.store.save(record)

        result = await api.rerun_task("p", record.id)
        assert result == {"queued": True}
        await api.aclose()

    asyncio.run(scenario())


def test_update_budget_round_trips_config(tmp_path: Path) -> None:
    app, api = make_api(tmp_path)

    async def scenario() -> None:
        saved = await api.update_budget({"monthly_usd_limit": 12.5})
        assert saved["budget"]["monthly_usd_limit"] == 12.5
        budget = await api.get_budget()
        assert budget["monthly_usd_limit"] == 12.5
        await api.aclose()

    asyncio.run(scenario())
