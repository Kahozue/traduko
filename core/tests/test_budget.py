import json
from pathlib import Path

import pytest

from traduko.budget import BUILTIN_PRICES, BudgetExceededError, BudgetMeter, load_prices
from traduko.config import BudgetConfig, CoreConfig
from traduko.events import Event, EventBus
from traduko.llm import ChatMessage, ChatRequest, ChatResponse, Usage, create_llm


class StubProvider:
    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="ok",
            model=request.model,
            usage=Usage(prompt_tokens=1000, completion_tokens=1000),
        )


def make_request() -> ChatRequest:
    return ChatRequest(model="stub-model", messages=[ChatMessage(role="user", content="hi")])


def write_pricing(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "pricing.yaml").write_text(
        "stub-model:\n  input: 1000.0\n  output: 1000.0\n", encoding="utf-8"
    )


def make_meter(root: Path, task_limit: float | None = None, monthly_limit: float | None = None):
    bus = EventBus()
    events: list[Event] = []
    bus.subscribe(events.append)
    config = CoreConfig(
        budget=BudgetConfig(task_usd_limit=task_limit, monthly_usd_limit=monthly_limit)
    )
    return BudgetMeter(root, bus, config), events


def test_records_cost_and_ledger(tmp_path: Path) -> None:
    write_pricing(tmp_path)
    meter, _ = make_meter(tmp_path)
    meter.chat(StubProvider(), make_request(), project="p", task_id="t1")
    assert meter.task_usage_usd("t1") == pytest.approx(2.0)
    assert meter.month_usage_usd() == pytest.approx(2.0)
    ledger_files = list((tmp_path / "budget").glob("ledger-*.jsonl"))
    assert len(ledger_files) == 1
    record = json.loads(ledger_files[0].read_text(encoding="utf-8").splitlines()[0])
    assert record["task_id"] == "t1" and record["cost_usd"] == pytest.approx(2.0)
    assert record["price_known"] is True
    assert record["kind"] == "chat"


def test_task_cap_blocks_and_emits_event(tmp_path: Path) -> None:
    write_pricing(tmp_path)
    meter, events = make_meter(tmp_path, task_limit=3.0)
    meter.chat(StubProvider(), make_request(), project="p", task_id="t1")
    meter.chat(StubProvider(), make_request(), project="p", task_id="t1")
    with pytest.raises(BudgetExceededError):
        meter.chat(StubProvider(), make_request(), project="p", task_id="t1")
    assert [e.type for e in events if e.type == "budget_exceeded"] == ["budget_exceeded"]
    warning_events = [e for e in events if e.type == "budget_warning"]
    assert len(warning_events) == 1
    assert warning_events[0].data["scope"] == "task"


def test_monthly_cap(tmp_path: Path) -> None:
    write_pricing(tmp_path)
    meter, events = make_meter(tmp_path, monthly_limit=2.0)
    meter.chat(StubProvider(), make_request(), project="p", task_id="t1")
    with pytest.raises(BudgetExceededError):
        meter.chat(StubProvider(), make_request(), project="p", task_id="t2")
    assert events[-1].data["scope"] == "month"


def test_new_meter_reloads_totals_from_ledger(tmp_path: Path) -> None:
    write_pricing(tmp_path)
    meter, _ = make_meter(tmp_path)
    meter.chat(StubProvider(), make_request(), project="p", task_id="t1")
    reloaded, _ = make_meter(tmp_path)
    assert reloaded.task_usage_usd("t1") == pytest.approx(2.0)
    assert reloaded.month_usage_usd() == pytest.approx(2.0)


def test_unknown_model_costs_zero(tmp_path: Path) -> None:
    meter, _ = make_meter(tmp_path)
    meter.chat(StubProvider(), make_request(), project="p", task_id="t1")
    assert meter.task_usage_usd("t1") == 0.0


def test_load_prices_merges_override(tmp_path: Path) -> None:
    write_pricing(tmp_path)
    prices = load_prices(tmp_path)
    assert prices["stub-model"] == (1000.0, 1000.0)
    for model in BUILTIN_PRICES:
        assert model in prices


def test_remaining_usd_uncapped_is_none(tmp_path: Path) -> None:
    meter = BudgetMeter(tmp_path / "a", EventBus(), CoreConfig())
    assert meter.remaining_usd("t1") is None


def test_remaining_usd_is_min_of_caps(tmp_path: Path) -> None:
    config = CoreConfig(
        budget=BudgetConfig(task_usd_limit=1.0, monthly_usd_limit=0.5)
    )
    meter = BudgetMeter(tmp_path / "b", EventBus(), config)
    assert meter.remaining_usd("t1") == 0.5


def test_remaining_usd_decreases_with_spend(tmp_path: Path) -> None:
    config = CoreConfig(budget=BudgetConfig(task_usd_limit=1.0))
    meter = BudgetMeter(tmp_path / "c", EventBus(), config)
    provider = create_llm({"type": "fake"})
    request = ChatRequest(
        model="gpt-4o", messages=[ChatMessage(role="user", content="x" * 4000)]
    )
    meter.chat(provider, request, project="p", task_id="t1")
    remaining = meter.remaining_usd("t1")
    assert remaining is not None and 0 < remaining < 1.0

# --- cloud ASR billing (v3-10): duration-priced, same ledger and caps ---


def test_record_asr_bills_by_duration(tmp_path: Path) -> None:
    meter, _ = make_meter(tmp_path)
    cost = meter.record_asr("whisper-1", 600.0, project="p", task_id="t1")
    assert cost == pytest.approx(0.06)
    assert meter.task_usage_usd("t1") == pytest.approx(0.06)
    assert meter.month_usage_usd() == pytest.approx(0.06)
    ledger = list((tmp_path / "budget").glob("ledger-*.jsonl"))[0]
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert row["kind"] == "asr"
    assert row["model"] == "whisper-1"
    assert row["seconds"] == 600.0
    assert row["cost_usd"] == pytest.approx(0.06)
    assert row["price_known"] is True


def test_record_asr_unknown_model_leaves_zero_cost_trace(tmp_path: Path) -> None:
    meter, _ = make_meter(tmp_path)
    cost = meter.record_asr("groq-whisper-v3", 120.0, project="p", task_id="t1")
    assert cost == 0.0
    assert meter.task_usage_usd("t1") == 0.0
    ledger = list((tmp_path / "budget").glob("ledger-*.jsonl"))[0]
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert row["price_known"] is False and row["cost_usd"] == 0.0


def test_pricing_yaml_feeds_both_tables_by_shape(tmp_path: Path) -> None:
    from traduko.budget import load_asr_prices

    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "pricing.yaml").write_text(
        "stub-model:\n  input: 1.0\n  output: 2.0\n"
        "whisper-1:\n  per_minute: 0.012\n"
        "my-custom-asr:\n  per_minute: 0.03\n",
        encoding="utf-8",
    )
    chat = load_prices(tmp_path)
    asr = load_asr_prices(tmp_path)
    assert chat["stub-model"] == (1.0, 2.0)
    assert "whisper-1" not in chat
    assert asr["whisper-1"] == 0.012  # override beats the builtin
    assert asr["my-custom-asr"] == 0.03
    assert "stub-model" not in asr


def test_asr_spend_counts_toward_caps_and_warns(tmp_path: Path) -> None:
    meter, events = make_meter(tmp_path, task_limit=0.01)
    meter.ensure_headroom("p", "t1")
    # 90s at 0.006/min = 0.009: past the 80% warning line, under the cap.
    meter.record_asr("whisper-1", 90.0, project="p", task_id="t1")
    assert any(e.type == "budget_warning" for e in events)
    meter.record_asr("whisper-1", 60.0, project="p", task_id="t1")
    with pytest.raises(BudgetExceededError):
        meter.ensure_headroom("p", "t1")


def test_asr_rows_reload_into_totals(tmp_path: Path) -> None:
    meter, _ = make_meter(tmp_path)
    meter.record_asr("whisper-1", 600.0, project="p", task_id="t1")
    reloaded, _ = make_meter(tmp_path)
    assert reloaded.task_usage_usd("t1") == pytest.approx(0.06)
    assert reloaded.month_usage_usd() == pytest.approx(0.06)
