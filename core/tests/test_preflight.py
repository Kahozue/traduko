from pathlib import Path

from traduko import preflight
from traduko.config import BudgetConfig, CoreConfig, save_config
from traduko.models import StageRecord, StageStatus, TaskRecord, utc_now_iso
from traduko.preflight import FAIL, OK, PreflightCheck, run_preflight


def make_record(
    tmp_path: Path, stages: list[StageRecord], *, with_input: bool = True
) -> TaskRecord:
    input_path = tmp_path / "in.srt"
    if with_input:
        input_path.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8"
        )
    now = utc_now_iso()
    return TaskRecord(
        id="t1", project="p", input_path=str(input_path), profile="x",
        stages=stages, created_at=now, updated_at=now,
    )


def test_missing_input_fails(tmp_path: Path) -> None:
    record = make_record(tmp_path, [StageRecord(type="noop")], with_input=False)
    report = run_preflight(record, tmp_path)
    assert report.ok is False
    assert [c.name for c in report.failures()] == ["input"]


def test_ok_when_uncapped(tmp_path: Path) -> None:
    record = make_record(tmp_path, [StageRecord(type="noop")])
    report = run_preflight(record, tmp_path)
    assert report.ok is True
    budget = next(c for c in report.checks if c.name == "budget")
    assert budget.level == OK and budget.message == "uncapped"


def test_budget_exhausted_fails(tmp_path: Path) -> None:
    save_config(
        tmp_path, CoreConfig(budget=BudgetConfig(task_usd_limit=0.0))
    )
    record = make_record(tmp_path, [StageRecord(type="noop")])
    report = run_preflight(record, tmp_path)
    assert report.ok is False
    assert [c.name for c in report.failures()] == ["budget"]


def test_completed_stages_are_skipped(tmp_path: Path, monkeypatch) -> None:
    def dummy_check(stage, root, config):
        return [PreflightCheck("dummy", FAIL, "always fails")]

    monkeypatch.setitem(preflight.STAGE_CHECKS, "dummy", dummy_check)
    record = make_record(
        tmp_path,
        [
            StageRecord(type="dummy", status=StageStatus.COMPLETED),
            StageRecord(type="dummy"),
        ],
    )
    report = run_preflight(record, tmp_path)
    failures = report.failures()
    assert len(failures) == 1
    assert failures[0].name == "stage 2 (dummy): dummy"


def test_unknown_stage_type_produces_no_checks(tmp_path: Path) -> None:
    record = make_record(tmp_path, [StageRecord(type="mystery")])
    report = run_preflight(record, tmp_path)
    assert [c.name for c in report.checks] == ["input", "budget"]
