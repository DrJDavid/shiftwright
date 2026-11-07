"""Store.school_week selects which minor_limits rules apply (SEMANTICS #8)."""
from __future__ import annotations

import pytest

from engine_fixtures import emp, tiny_store
from shiftwright_engine import solve_week
from shiftwright_engine.prep import build_prep
from shiftwright_validator import validate


def _with_15yo(school_week):
    cfg = tiny_store()
    store = cfg.store.model_copy(update={"school_week": school_week})
    return cfg.model_copy(update={"store": store, "employees": cfg.employees + [emp("e15", ["cashier"], age=15)]})


def _caps(school_week):
    p = build_prep(_with_15yo(school_week), prune=False)
    e = p.emps["e15"]
    mon = max(c.paid_min for c in p.by_emp_day[("e15", 0)])
    week = min(c for c, _, _ in p.effective_max_minutes(e))
    return mon, week


@pytest.mark.parametrize("school_week", [None, True])
def test_school_week_rules_apply(school_week):
    mon, week = _caps(school_week)
    assert mon <= 3 * 60  # school day: 3 h
    assert week <= 18 * 60


def test_non_school_week_uses_only_non_school_rules():
    mon, week = _caps(False)
    assert mon > 3 * 60 and mon <= 8 * 60
    assert week > 18 * 60


@pytest.mark.parametrize("school_week", [None, True, False])
def test_solve_passes_validator(school_week):
    cfg = _with_15yo(school_week)
    s = solve_week(cfg, time_limit_s=10)
    assert s.status in ("optimal", "feasible"), s.solver_stats
    rep = validate(cfg, s)
    assert [v for v in rep.violations if v.severity == "hard"] == []
