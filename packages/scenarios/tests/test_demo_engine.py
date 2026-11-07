"""Demo store against the real engine (skips until shiftwright_engine.solve_week lands)."""
import pytest

from shiftwright_scenarios.verify_demo import engine_functions, verify


@pytest.fixture(scope="module")
def report():
    solve_week, fix_day = engine_functions()
    if solve_week is None:
        pytest.skip("shiftwright_engine.solve_week not available yet")
    return verify(30, solve_week, fix_day)


def test_demo_solves(report):
    assert report["status"] in ("optimal", "feasible")


def test_saturday_callouts_are_scheduled_saturday_morning(report):
    assert report["callouts_ok"], report["callouts"]


def test_demo_phones_rank_first_for_outreach(report):
    assert not report["demo_phones_scheduled_saturday"]
    assert report["proxy_phones_ok"], report["proxy_ranking_top5"]
    if "fix" in report:
        assert report["fix_phones_ok"], report["fix"]["outreach_queue"]
