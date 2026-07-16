"""Reply text for the Discord bot.

User-facing strings are Traditional Chinese by product convention; like the
tray menu on the Rust side, this module is a deliberate exception to the
English-only source rule. Wording mirrors app/src/i18n/zh-TW.ts.
"""
from __future__ import annotations

STATUS_LABELS = {
    "pending": "等待中",
    "running": "執行中",
    "waiting_review": "待人工確認",
    "paused": "已暫停",
    "completed": "已完成",
    "failed": "失敗",
    "canceled": "已取消",
    "skipped": "已略過",
}

STAGE_LABELS = {
    "ingest_subtitle": "讀入字幕",
    "extract_audio": "抽取音軌",
    "asr": "語音辨識",
    "segment": "斷句",
    "translate": "翻譯",
    "export_subtitles": "輸出字幕",
    "hardburn": "硬燒字幕",
    "proofread": "AI 校對",
    "noop": "空階段",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def stage_label(stage_type: str) -> str:
    return STAGE_LABELS.get(stage_type, stage_type)


def bar(current: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "░" * width
    filled = round(width * min(current, total) / total)
    return "█" * filled + "░" * (width - filled)


def task_label(row: dict) -> str:
    name = row.get("name") or row["id"]
    return f"{name}（{row['project']}/{row['id']}）"


def render_task_list(rows: list[dict], limit: int = 8) -> str:
    if not rows:
        return "目前沒有任何任務。"
    lines = ["最近任務："]
    for row in rows[:limit]:
        lines.append(f"- {status_label(row['status'])}｜{task_label(row)}")
    return "\n".join(lines)


def render_task_detail(record: dict) -> str:
    lines = [task_label(record), f"狀態：{status_label(record['status'])}"]
    for i, stage in enumerate(record["stages"], start=1):
        lines.append(f"{i}. {stage_label(stage['type'])}：{status_label(stage['status'])}")
    return "\n".join(lines)


def _money(value: float | None) -> str:
    return "未設上限" if value is None else f"{value:.2f} USD"


def render_budget(budget: dict) -> str:
    return (
        f"本月已用：{budget['month_usd']:.2f} USD\n"
        f"單任務上限：{_money(budget['task_usd_limit'])}\n"
        f"每月上限：{_money(budget['monthly_usd_limit'])}"
    )
