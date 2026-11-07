"""Engine regression (black box): engine schedules must pass the validator.

Marked slow (~70 s). Skip with `-m "not slow"`. The full audit is
`uv run python packages/validator/scripts/audit_engine.py` (see STATUS.md).
"""
from __future__ import annotations

import pytest

engine = pytest.importorskip("shiftwright_engine")
pytest.importorskip("shiftwright_scenarios")
pytest.importorskip("shiftwright_laws")

from shiftwright_contracts.models import FixRequest  # noqa: E402
from shiftwright_scenarios import load_demo_store, load_tiny_store, pick_callouts  # noqa: E402
from shiftwright_validator.audit import (  # noqa: E402
    Case,
    audit_cases,
    audit_fix,
    classify,
    classify_fix,
    default_cases,
    with_law_pack,
)

pytestmark = pytest.mark.slow


def small_cases():
    cases = default_cases(seeds=[1], difficulties=[("easy", "TX"), ("legal_trap", "TX")], fixtures=False)
    tiny = with_law_pack(load_tiny_store())
    rows = [("tiny_store", tiny, 5)] + [(c.name, c.config, 15) for c in cases]
    return [pytest.param(*row, id=row[0]) for row in rows]


@pytest.mark.parametrize("name,config,limit", small_cases())
def test_engine_schedule_passes_validator(name, config, limit):
    [result] = list(audit_cases([Case(name, config)], time_limit_s=limit))
    assert result.status in ("optimal", "feasible"), result.line()
    assert result.disagreements == [], result.disagreements
    # legal_trap's below-minimum-wage employee is scheduled and flagged (SEMANTICS #15)
    if "legal_trap" in name:
        assert any("below_minimum_wage" in e for e in result.expected)


def test_infeasible_empty_schedule_is_not_a_disagreement():
    tiny = with_law_pack(load_tiny_store())
    tiny.employees = [e for e in tiny.employees if "leader_on_duty" not in e.trained_role_ids]
    schedule = engine.solve_week(tiny, time_limit_s=5)
    assert schedule.status == "infeasible"
    _, found, expected = classify(tiny, schedule)
    assert found == [] and expected


needs_fix_day = pytest.mark.skipif(not hasattr(engine, "fix_day"), reason="shiftwright_engine.fix_day not on main")


@needs_fix_day
def test_fix_day_plans_pass_validator():
    config = with_law_pack(load_tiny_store())
    schedule = engine.solve_week(config, time_limit_s=5)
    day = schedule.shifts[0].day
    callouts = pick_callouts(config, schedule, day, n=1)
    assert callouts, "tiny_store schedule has nobody to call out"
    req = FixRequest(config=config, schedule=schedule, callouts=callouts, day=day,
                     now=callouts[0].reported_at)
    plan = engine.fix_day(req, time_limit_s=8)
    found, _ = classify_fix(req, plan)
    assert found == [], found


@pytest.fixture(scope="module")
def demo_week():
    config = with_law_pack(load_demo_store())
    return config, engine.solve_week(config, time_limit_s=30)


@needs_fix_day
@pytest.mark.parametrize("mode", [None, "one_to_one"])
def test_demo_saturday_callouts_pass_validate_fix(demo_week, mode):
    """The demo script: Saturday 06:04, e034 / e052 / e053 call out."""
    config, schedule = demo_week
    [result] = list(audit_fix(Case("demo_store", config), schedule, day=5, now=364, modes=(mode,),
                              callout_ids=["e034", "e052", "e053"]))
    assert result.disagreements == [], result.disagreements
