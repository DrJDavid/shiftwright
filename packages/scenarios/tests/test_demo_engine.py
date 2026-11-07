"""Demo store against the real engine (skips until shiftwright_engine.solve_week lands).

Uses the API's default solve time (30 s): the demo has to work with what the app actually runs.
"""
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
    assert report["callouts_ok"], (report["callouts"], report.get("repick"))


def test_repair_possible_but_not_trivial(report):
    assert report["repair_not_trivial"], report["lost_hours_by_role"]
    assert report["repair_possible"], report["plausible_callins"]
    if "fix" in report:
        fix = report["fix"]
        assert fix["outreach_queue"]
        assert fix["coverage_after_best_pct"] > fix["coverage_before_pct"]
