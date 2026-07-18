import pytest

from traduko.dubbing.align import plan_segment


def test_fit_within_tolerance() -> None:
    plan = plan_segment(2.0, 2.1, tolerance=1.1, max_tempo=1.4, can_regen=True)
    assert plan == {"action": "fit", "tempo": 1.0}


def test_over_window_asks_for_regen_first() -> None:
    plan = plan_segment(2.0, 3.0, tolerance=1.1, max_tempo=1.4, can_regen=True)
    assert plan == {"action": "regen", "tempo": 1.0}


def test_still_over_after_regen_gets_atempo() -> None:
    plan = plan_segment(2.0, 2.6, tolerance=1.1, max_tempo=1.4, can_regen=False)
    assert plan["action"] == "atempo"
    # tempo compresses the audio to exactly window * tolerance
    assert plan["tempo"] == pytest.approx(2.6 / 2.2, abs=0.001)


def test_tempo_capped_at_max_reports_overflow() -> None:
    plan = plan_segment(2.0, 4.0, tolerance=1.1, max_tempo=1.4, can_regen=False)
    assert plan == {"action": "overflow", "tempo": 1.4}


def test_zero_window_is_overflow() -> None:
    plan = plan_segment(0.0, 1.0, tolerance=1.1, max_tempo=1.4, can_regen=False)
    assert plan == {"action": "overflow", "tempo": 1.4}


def test_zero_duration_fits() -> None:
    plan = plan_segment(2.0, 0.0, tolerance=1.1, max_tempo=1.4, can_regen=True)
    assert plan == {"action": "fit", "tempo": 1.0}
