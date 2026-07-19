"""Slash command handlers, free of any discord dependency.

Each handler takes the core API plus plain arguments and returns the reply
text, so tests drive them against a real in-process service. Replies are
zh-TW user-facing copy (same deliberate exception as render.py).
"""
from __future__ import annotations

from . import render
from .api import CoreApi, CoreApiError

UNAUTHORIZED = "未授權的使用者。請在 Traduko 設定頁將你的 Discord 使用者 ID 加入允許清單。"


def is_authorized(user_id: object, allowed_user_ids: list[str]) -> bool:
    return str(user_id) in allowed_user_ids


def _not_found(task_id: str) -> str:
    return f"找不到任務 {task_id}。"


async def status_command(api: CoreApi, task_id: str | None = None) -> str:
    if not task_id:
        return render.render_task_list(await api.list_tasks())
    row = await api.find_task(task_id.strip())
    if row is None:
        return _not_found(task_id)
    record = await api.get_task(row["project"], row["id"])
    return render.render_task_detail(record)


async def pause_command(api: CoreApi, task_id: str) -> str:
    row = await api.find_task(task_id.strip())
    if row is None:
        return _not_found(task_id)
    try:
        await api.pause_task(row["project"], row["id"])
    except CoreApiError as error:
        return f"無法暫停：{error.detail}"
    return f"已要求暫停 {render.task_label(row)}，將在安全點停下。"


async def resume_command(api: CoreApi, task_id: str) -> str:
    row = await api.find_task(task_id.strip())
    if row is None:
        return _not_found(task_id)
    try:
        await api.run_task(row["project"], row["id"])
    except CoreApiError as error:
        detail = error.detail
        if isinstance(detail, dict) and "checks" in detail:
            failures = "\n".join(
                f"- {check['name']}：{check['message']}" for check in detail["checks"]
            )
            return f"預檢未通過：\n{failures}"
        return f"無法執行：{detail}"
    return f"已將 {render.task_label(row)} 排入執行佇列。"


async def rerun_command(api: CoreApi, task_id: str) -> str:
    row = await api.find_task(task_id.strip())
    if row is None:
        return _not_found(task_id)
    try:
        await api.rerun_task(row["project"], row["id"])
    except CoreApiError as error:
        detail = error.detail
        if isinstance(detail, dict) and "checks" in detail:
            failures = "\n".join(
                f"- {check['name']}：{check['message']}" for check in detail["checks"]
            )
            return f"預檢未通過：\n{failures}"
        return f"無法執行：{detail}"
    return f"已將 {render.task_label(row)} 排入重新執行佇列。"


async def cancel_command(api: CoreApi, task_id: str) -> str:
    row = await api.find_task(task_id.strip())
    if row is None:
        return _not_found(task_id)
    try:
        await api.cancel_task(row["project"], row["id"])
    except CoreApiError as error:
        return f"無法取消：{error.detail}"
    return f"已取消 {render.task_label(row)}。"


def _parse_limit(raw: str) -> float | None:
    text = raw.strip().lower()
    if text == "off":
        return None
    value = float(text)
    if value < 0:
        raise ValueError(raw)
    return value


async def budget_command(
    api: CoreApi, task_limit: str | None = None, monthly_limit: str | None = None
) -> str:
    updates: dict[str, float | None] = {}
    try:
        if task_limit is not None:
            updates["task_usd_limit"] = _parse_limit(task_limit)
        if monthly_limit is not None:
            updates["monthly_usd_limit"] = _parse_limit(monthly_limit)
    except ValueError:
        return "上限須為不小於 0 的數字，或 off 表示不設上限。"
    if updates:
        try:
            await api.update_budget(updates)
        except CoreApiError as error:
            return f"無法更新預算：{error.detail}"
    return render.render_budget(await api.get_budget())
