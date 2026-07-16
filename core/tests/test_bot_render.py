from traduko.bot import render


def test_bar_proportions() -> None:
    assert render.bar(0, 10, width=10) == "░" * 10
    assert render.bar(10, 10, width=10) == "█" * 10
    assert render.bar(5, 10, width=10) == "█" * 5 + "░" * 5
    assert render.bar(3, 0, width=10) == "░" * 10


def test_task_list_renders_names_and_statuses() -> None:
    rows = [
        {"id": "t1", "project": "p", "status": "running", "name": "my-video"},
        {"id": "t2", "project": "p", "status": "completed", "name": None},
    ]
    text = render.render_task_list(rows)
    assert "執行中" in text and "my-video（p/t1）" in text
    assert "已完成" in text and "t2（p/t2）" in text
    assert render.render_task_list([]) == "目前沒有任何任務。"


def test_task_list_limits_rows() -> None:
    rows = [
        {"id": f"t{i}", "project": "p", "status": "pending", "name": None}
        for i in range(12)
    ]
    text = render.render_task_list(rows, limit=8)
    assert "t7" in text and "t8" not in text


def test_task_detail_lists_stages() -> None:
    record = {
        "id": "t1", "project": "p", "status": "paused", "name": "ep01",
        "stages": [
            {"type": "translate", "status": "completed"},
            {"type": "export_subtitles", "status": "pending"},
        ],
    }
    text = render.render_task_detail(record)
    assert "ep01（p/t1）" in text and "已暫停" in text
    assert "1. 翻譯：已完成" in text
    assert "2. 輸出字幕：等待中" in text


def test_budget_rendering() -> None:
    text = render.render_budget(
        {"month_usd": 1.5, "task_usd_limit": None, "monthly_usd_limit": 20.0}
    )
    assert "1.50 USD" in text and "未設上限" in text and "20.00 USD" in text
