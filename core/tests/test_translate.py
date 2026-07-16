import json
from pathlib import Path

import pytest

from traduko.budget import BudgetExceededError, BudgetMeter
from traduko.config import BudgetConfig, CoreConfig
from traduko.events import EventBus
from traduko.llm import ChatRequest, ChatResponse, Usage, create_llm
from traduko.prompts import DEFAULT_TEMPLATES
from traduko.translate import (
    TranslationError,
    TranslationPaused,
    TranslationSettings,
    translate_segments,
)


def seg(id_: int, text: str) -> dict:
    return {"id": id_, "start": float(id_), "end": float(id_) + 0.9, "text": text}


def make_meter(tmp_path: Path, task_limit: float | None = None) -> BudgetMeter:
    config = CoreConfig(budget=BudgetConfig(task_usd_limit=task_limit))
    return BudgetMeter(tmp_path, EventBus(), config)


def make_settings(**overrides) -> TranslationSettings:
    defaults = dict(
        source_language="en", target_language="zh-TW", model="fake-model", batch_size=2
    )
    defaults.update(overrides)
    return TranslationSettings(**defaults)


def run_translate(tmp_path: Path, segments, provider, settings=None, meter=None):
    progress: list[tuple[int, int]] = []
    result = translate_segments(
        segments,
        settings or make_settings(),
        provider,
        meter or make_meter(tmp_path),
        [],
        DEFAULT_TEMPLATES["translate"],
        project="p",
        task_id="t1",
        partial_path=tmp_path / "partial.json",
        emit_progress=lambda done, total: progress.append((done, total)),
    )
    return result, progress


def test_happy_path_batches_and_aligns(tmp_path: Path) -> None:
    provider = create_llm({"type": "fake"})
    segments = [seg(1, "one"), seg(2, "two"), seg(3, "three")]
    result, progress = run_translate(tmp_path, segments, provider)
    assert [r["target"] for r in result] == ["[T] one", "[T] two", "[T] three"]
    assert result[0]["source"] == "one" and result[0]["start"] == 1.0
    assert progress == [(0, 3), (2, 3), (3, 3)]
    partial = json.loads((tmp_path / "partial.json").read_text(encoding="utf-8"))
    assert len(partial) == 3


class CountingFake:
    def __init__(self) -> None:
        self.calls = 0
        self.inner = create_llm({"type": "fake"})

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        return self.inner.chat(request)


def test_resume_skips_done_segments(tmp_path: Path) -> None:
    (tmp_path / "partial.json").write_text(
        json.dumps([{"id": 1, "start": 1.0, "end": 1.9, "source": "one", "target": "done"}]),
        encoding="utf-8",
    )
    provider = CountingFake()
    segments = [seg(1, "one"), seg(2, "two")]
    result, _ = run_translate(
        tmp_path, segments, provider, settings=make_settings(batch_size=10)
    )
    assert provider.calls == 1
    assert [r["target"] for r in result] == ["done", "[T] two"]


class GarbageThenValid:
    def __init__(self, garbage_times: int) -> None:
        self.remaining = garbage_times
        self.inner = create_llm({"type": "fake"})
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            return ChatResponse(content="sorry, no json", model=request.model, usage=Usage(1, 1))
        return self.inner.chat(ChatRequest(model=request.model, messages=request.messages[:1]))


def test_malformed_response_retries_once(tmp_path: Path) -> None:
    provider = GarbageThenValid(garbage_times=1)
    result, _ = run_translate(
        tmp_path, [seg(1, "one")], provider, settings=make_settings(batch_size=10)
    )
    assert provider.calls == 2
    assert result[0]["target"] == "[T] one"


def test_persistent_garbage_raises(tmp_path: Path) -> None:
    provider = GarbageThenValid(garbage_times=5)
    with pytest.raises(TranslationError):
        run_translate(tmp_path, [seg(1, "one")], provider, settings=make_settings(batch_size=10))


def test_budget_exceeded_propagates_with_partial_saved(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pricing.yaml").write_text(
        "fake-model:\n  input: 1000000.0\n  output: 1000000.0\n", encoding="utf-8"
    )
    meter = make_meter(tmp_path, task_limit=0.5)
    provider = create_llm({"type": "fake"})
    segments = [seg(1, "one"), seg(2, "two"), seg(3, "three")]
    with pytest.raises(BudgetExceededError):
        run_translate(tmp_path, segments, provider, meter=meter)
    partial = json.loads((tmp_path / "partial.json").read_text(encoding="utf-8"))
    assert len(partial) == 2


def test_manual_pause_stops_between_batches_and_resumes(tmp_path: Path) -> None:
    provider = CountingFake()
    segments = [seg(1, "one"), seg(2, "two"), seg(3, "three"), seg(4, "four")]
    checks = iter([False, True])

    with pytest.raises(TranslationPaused):
        translate_segments(
            segments,
            make_settings(),
            provider,
            make_meter(tmp_path),
            [],
            DEFAULT_TEMPLATES["translate"],
            project="p",
            task_id="t1",
            partial_path=tmp_path / "partial.json",
            emit_progress=lambda done, total: None,
            should_pause=lambda: next(checks),
        )
    partial = json.loads((tmp_path / "partial.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in partial] == [1, 2]
    assert provider.calls == 1

    result, _ = run_translate(tmp_path, segments, provider)
    assert provider.calls == 2
    assert [r["target"] for r in result] == ["[T] one", "[T] two", "[T] three", "[T] four"]
