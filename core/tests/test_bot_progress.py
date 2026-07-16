import asyncio

from traduko.bot.progress import ProgressBoard, consume_events

RECORD = {
    "id": "t1",
    "project": "p",
    "name": "ep01",
    "stages": [{"type": "translate"}, {"type": "export_subtitles"}],
}


def payload(etype: str, data: dict | None = None) -> dict:
    return {"ts": "now", "type": etype, "task_id": "t1", "project": "p", "data": data or {}}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_board_posts_then_edits_and_throttles_progress() -> None:
    clock = FakeClock()
    board = ProgressBoard(clock=clock, min_edit_interval=2.0)

    action = board.handle(payload("task_started", {"stage_total": 2}), RECORD)
    assert action.kind == "post"
    assert "ep01（p/t1）" in action.content and "階段 1/2" in action.content

    action = board.handle(payload("stage_started", {"stage_index": 0, "stage_total": 2}))
    assert action.kind == "edit" and "翻譯" in action.content

    clock.now = 0.5
    assert (
        board.handle(payload("stage_progress", {"stage_index": 0, "current": 3, "total": 10}))
        is None
    )
    clock.now = 3.0
    action = board.handle(
        payload("stage_progress", {"stage_index": 0, "current": 5, "total": 10})
    )
    assert action.kind == "edit" and "5/10" in action.content and "█" in action.content


def test_board_closes_on_terminal_event_and_forgets_task() -> None:
    board = ProgressBoard(clock=FakeClock())
    board.handle(payload("task_started", {"stage_total": 2}), RECORD)
    action = board.handle(payload("task_completed", {"stage_total": 2}))
    assert action.kind == "close" and "已完成" in action.content
    assert (
        board.handle(payload("stage_progress", {"stage_index": 0, "current": 1, "total": 2}))
        is None
    )


def test_board_ignores_events_for_unknown_tasks() -> None:
    board = ProgressBoard(clock=FakeClock())
    assert board.handle(payload("stage_started", {"stage_index": 0})) is None


class FakeMessenger:
    def __init__(self) -> None:
        self.posts: list[str] = []
        self.edits: list[tuple[int, str]] = []

    async def post(self, content: str) -> int:
        self.posts.append(content)
        return len(self.posts)

    async def edit(self, ref: int, content: str) -> None:
        self.edits.append((ref, content))


class FakeApi:
    async def get_task(self, project: str, task_id: str) -> dict:
        return RECORD


def test_consumer_posts_edits_and_stops_on_sentinel() -> None:
    async def scenario() -> FakeMessenger:
        queue: asyncio.Queue = asyncio.Queue()
        board = ProgressBoard(clock=FakeClock())
        await queue.put(payload("task_started", {"stage_total": 2}))
        await queue.put(payload("stage_started", {"stage_index": 0, "stage_total": 2}))
        await queue.put(payload("task_failed", {"stage_index": 0, "error": "x"}))
        await queue.put(None)
        messenger = FakeMessenger()
        await consume_events(queue, FakeApi(), messenger, board)
        return messenger

    messenger = asyncio.run(scenario())
    assert len(messenger.posts) == 1
    assert len(messenger.edits) == 2
    assert "失敗" in messenger.edits[-1][1]
