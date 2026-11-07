"""Demo stores against the real engine (skips until shiftwright_engine.solve_week lands).

Uses the API's default solve time (30 s): the demo has to work with what the app actually runs.
Austin always runs. Chicago / Seattle / SF / restaurant add ~30 s each, so they run only with
SW_DEMO_ENGINE_ALL=1 (or use `uv run python -m shiftwright_scenarios.verify_demo 30 all`).
"""
import os

import pytest

from shiftwright_scenarios import DEMO_LOCALITIES, DEMO_STORES
from shiftwright_scenarios.verify_demo import engine_functions, verify

MIN_COVERAGE = {"austin": 90.0, "chicago": 88.0, "seattle": 85.0, "sf": 85.0, "restaurant": 88.0}
ALL = os.environ.get("SW_DEMO_ENGINE_ALL") == "1"
_cache: dict = {}


def report(loc: str) -> dict:
    if loc != "austin" and not ALL:
        pytest.skip("set SW_DEMO_ENGINE_ALL=1 to solve the non-Austin demo stores")
    solve_week, fix_day = engine_functions()
    if solve_week is None:
        pytest.skip("shiftwright_engine.solve_week not available yet")
    if loc not in _cache:
        _cache[loc] = verify(30, solve_week, fix_day, locality=loc)
    return _cache[loc]


@pytest.mark.parametrize("loc", DEMO_STORES)
def test_demo_solves_and_validates(loc):
    r = report(loc)
    assert r["status"] in ("optimal", "feasible")
    assert r["metrics"]["coverage_pct"] >= MIN_COVERAGE[loc], r["metrics"]
    if r["validator"] is not None:
        assert r["validator"]["passed"], r["validator"]["hard"]


@pytest.mark.parametrize("loc", DEMO_STORES)
def test_saturday_callouts_are_scheduled_saturday_morning(loc):
    r = report(loc)
    assert r["callouts_ok"], (r["callouts"], r.get("repick"))


@pytest.mark.parametrize("loc", DEMO_LOCALITIES)
def test_repair_possible_but_not_trivial(loc):  # retail stores; the restaurant has a small bench
    r = report(loc)
    assert r["repair_not_trivial"], r["lost_hours_by_role"]
    assert r["repair_possible"], r["plausible_callins"]
    if "fix" in r:
        fix = r["fix"]
        assert len(fix["outreach_queue"]) >= 3, fix["outreach_queue"]
        assert fix["coverage_after_best_pct"] > fix["coverage_before_pct"]
