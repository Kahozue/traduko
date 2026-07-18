from pathlib import Path

from traduko import preflight
from traduko.config import BudgetConfig, CoreConfig, save_config
from traduko.models import StageRecord, StageStatus, TaskRecord, utc_now_iso
from traduko.preflight import FAIL, OK, WARN, PreflightCheck, run_preflight


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


def test_ffmpeg_missing_fails_for_media_stages(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight, "ffmpeg_available", lambda: False)
    record = make_record(
        tmp_path, [StageRecord(type="extract_audio"), StageRecord(type="hardburn")]
    )
    report = run_preflight(record, tmp_path)
    assert [c.name for c in report.failures()] == [
        "stage 1 (extract_audio): ffmpeg",
        "stage 2 (hardburn): ffmpeg",
    ]


def test_ffmpeg_present_is_ok(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight, "ffmpeg_available", lambda: True)
    record = make_record(tmp_path, [StageRecord(type="extract_audio")])
    assert run_preflight(record, tmp_path).ok is True


def test_asr_missing_package_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight.asrsetup, "package_available", lambda: False)
    record = make_record(tmp_path, [StageRecord(type="asr")])
    report = run_preflight(record, tmp_path)
    failures = report.failures()
    assert len(failures) == 1 and "uv sync --extra asr" in failures[0].message


def test_asr_model_not_downloaded_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight.asrsetup, "package_available", lambda: True)
    monkeypatch.setattr(preflight.asrsetup, "model_cached", lambda size: False)
    record = make_record(
        tmp_path,
        [StageRecord(type="asr", params={"options": {"model_size": "medium"}})],
    )
    report = run_preflight(record, tmp_path)
    failures = report.failures()
    assert len(failures) == 1
    assert "medium" in failures[0].message
    assert "not downloaded" in failures[0].message


def test_asr_installed_notes_model_size(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight.asrsetup, "package_available", lambda: True)
    monkeypatch.setattr(preflight.asrsetup, "model_cached", lambda size: True)
    record = make_record(
        tmp_path,
        [StageRecord(type="asr", params={"options": {"model_size": "medium"}})],
    )
    report = run_preflight(record, tmp_path)
    assert report.ok is True
    check = next(c for c in report.checks if "asr model" in c.name)
    assert "medium" in check.message


def test_asr_custom_provider_produces_no_check(tmp_path: Path) -> None:
    record = make_record(
        tmp_path, [StageRecord(type="asr", params={"provider": "e2e-fake-asr"})]
    )
    report = run_preflight(record, tmp_path)
    assert [c.name for c in report.checks] == ["input", "budget"]


def test_llm_fake_provider_warns_without_config(tmp_path: Path) -> None:
    record = make_record(tmp_path, [StageRecord(type="translate")])
    report = run_preflight(record, tmp_path)
    assert report.ok is True
    check = next(c for c in report.checks if "llm provider" in c.name)
    assert check.level == WARN


def test_llm_fake_resolves_to_sole_real_provider(tmp_path: Path) -> None:
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={
                "cloud": {
                    "type": "openai_compat",
                    "base_url": "https://api.example.com/v1",
                    "api_key": "sk-test",
                }
            }
        ),
    )
    record = make_record(
        tmp_path, [StageRecord(type="translate", params={"provider": "fake"})]
    )
    report = run_preflight(record, tmp_path)
    assert report.ok is True
    check = next(c for c in report.checks if "llm provider" in c.name)
    assert check.level == OK and "cloud" in check.message


def test_llm_fake_with_multiple_providers_and_no_default_fails(
    tmp_path: Path,
) -> None:
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={
                "a": {"type": "openai_compat", "base_url": "https://a/v1"},
                "b": {"type": "openai_compat", "base_url": "https://b/v1"},
            }
        ),
    )
    record = make_record(tmp_path, [StageRecord(type="translate")])
    report = run_preflight(record, tmp_path)
    assert report.ok is False
    assert "default" in report.failures()[0].message


def test_llm_default_provider_selected_from_config(tmp_path: Path) -> None:
    save_config(
        tmp_path,
        CoreConfig(
            default_provider="b",
            llm_providers={
                "a": {"type": "openai_compat", "base_url": "https://a/v1"},
                "b": {
                    "type": "openai_compat",
                    "base_url": "https://b/v1",
                    "api_key": "sk-test",
                },
            },
        ),
    )
    record = make_record(tmp_path, [StageRecord(type="translate_chunks")])
    report = run_preflight(record, tmp_path)
    assert report.ok is True
    check = next(c for c in report.checks if "llm provider" in c.name)
    assert check.level == OK and "b" in check.message


def test_llm_unknown_provider_fails(tmp_path: Path) -> None:
    record = make_record(
        tmp_path, [StageRecord(type="proofread", params={"provider": "nope"})]
    )
    report = run_preflight(record, tmp_path)
    failures = report.failures()
    assert len(failures) == 1 and "unknown llm provider" in failures[0].message


def test_llm_api_key_env_checked(tmp_path: Path, monkeypatch) -> None:
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={
                "cloud": {
                    "type": "openai_compat",
                    "base_url": "https://api.example.com/v1",
                    "api_key_env": "TRADUKO_TEST_KEY",
                }
            }
        ),
    )
    record = make_record(
        tmp_path, [StageRecord(type="translate", params={"provider": "cloud"})]
    )
    monkeypatch.delenv("TRADUKO_TEST_KEY", raising=False)
    report = run_preflight(record, tmp_path)
    assert report.ok is False
    assert "TRADUKO_TEST_KEY" in report.failures()[0].message

    monkeypatch.setenv("TRADUKO_TEST_KEY", "sk-test")
    assert run_preflight(record, tmp_path).ok is True


def test_llm_keyless_openai_compat_warns(tmp_path: Path) -> None:
    save_config(
        tmp_path,
        CoreConfig(
            llm_providers={
                "local": {
                    "type": "openai_compat",
                    "base_url": "http://localhost:11434/v1",
                }
            }
        ),
    )
    record = make_record(
        tmp_path, [StageRecord(type="translate", params={"provider": "local"})]
    )
    report = run_preflight(record, tmp_path)
    assert report.ok is True
    check = next(c for c in report.checks if "llm provider" in c.name)
    assert check.level == WARN


def test_llm_scripted_provider_needs_no_key(tmp_path: Path) -> None:
    save_config(
        tmp_path,
        CoreConfig(llm_providers={"agent": {"type": "scripted", "responses": []}}),
    )
    record = make_record(
        tmp_path, [StageRecord(type="proofread", params={"provider": "agent"})]
    )
    report = run_preflight(record, tmp_path)
    assert report.ok is True
    check = next(c for c in report.checks if "llm provider" in c.name)
    assert check.level == OK
