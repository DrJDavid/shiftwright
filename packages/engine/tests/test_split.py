"""Split shifts (SEMANTICS #23, Store.max_shifts_per_day)."""
from __future__ import annotations

import pytest
from engine_fixtures import tiny_store, with_law
from shiftwright_contracts.models import (
    CallOut,
    DayHours,
    DemandRequirement,
    DemandSource,
    FixRequest,
    Jurisdiction,
)
from shiftwright_engine import fix_day, solve_week
from shiftwright_engine.bounds import always_staffed_conflict
from shiftwright_engine.prep import build_prep
from shiftwright_validator import validate


def _hard(cfg, s):
    return [f"{v.code.value}: {v.message}" for v in validate(cfg, s).violations
            if v.severity == "hard" or v.code.value == "metrics_mismatch"]


def _two_peaks(n: int, peaks=((480, 720), (1020, 1260)), state="TX", overtime=False, heads=(1, 1),
               staff=("e3",)):
    """Cashiers (e3 by default), Friday only, demand in two peaks too far apart for one 10 h shift."""
    cfg = tiny_store()
    store = cfg.store.model_copy(update={"hours": [DayHours(day=4, open=420, close=1320)], "max_shifts_per_day": n,
                                         "pre_open_minutes": 0, "post_close_minutes": 0})
    demand = [DemandRequirement(id=f"d{i}", role_id="cashier", day=4, start=a, end=b, headcount=h,
                                source=DemandSource.corporate) for i, ((a, b), h) in enumerate(zip(peaks, heads))]
    emps = [e.model_copy(update={"wage_per_hour": 20.0}) for e in cfg.employees if e.id in staff]
    cfg = cfg.model_copy(update={
        "store": store, "demand": demand, "employees": emps,
        "constraints": [c for c in cfg.constraints if c.id in ("c_min_shift", "c_max_shift", "c_min_rest")],
        "budget": cfg.budget.model_copy(update={"overtime_allowed": overtime}),
    })
    return with_law(cfg, Jurisdiction(state=state, city=None))


def test_one_shift_per_day_by_default():
    cfg = _two_peaks(1)
    s = solve_week(cfg, time_limit_s=10)
    assert len([x for x in s.shifts if x.day == 4]) == 1
    assert s.gaps and _hard(cfg, s) == []


def test_split_shift_covers_both_peaks():
    cfg = _two_peaks(2)
    s = solve_week(cfg, time_limit_s=10)
    mine = sorted((x for x in s.shifts if x.day == 4), key=lambda x: x.start)
    assert len(mine) == 2
    assert mine[0].end < mine[1].start  # never overlapping or back to back
    assert len({x.id for x in s.shifts}) == len(s.shifts)
    assert not s.gaps and s.metrics.coverage_pct == 100.0
    assert _hard(cfg, s) == []


def test_split_day_daily_overtime_cap_sums_both_shifts():
    """CA daily OT is per day (#4, #23): with overtime not allowed, both shifts together stay ≤ 8 h."""
    peaks = ((420, 720), (900, 1260))  # 5 h + 6 h
    cfg = _two_peaks(2, peaks, state="CA", overtime=False)
    s = solve_week(cfg, time_limit_s=10)
    paid = sum((x.end - x.start) - sum(b.end - b.start for b in x.breaks if not b.paid)
               for x in s.shifts if x.day == 4)
    assert paid <= 8 * 60
    assert _hard(cfg, s) == []


def test_split_day_daily_overtime_is_paid_on_the_day_total():
    peaks = ((420, 720), (900, 1260))
    cfg = _two_peaks(2, peaks, state="CA", overtime=True)
    s = solve_week(cfg, time_limit_s=10)
    assert len([x for x in s.shifts if x.day == 4]) == 2
    assert s.metrics.overtime_hours > 0
    assert _hard(cfg, s) == []


def test_fix_day_keeps_split_shifts():
    """One cashier splits, the other works the morning peak only and calls out."""
    cfg = _two_peaks(2, heads=(2, 1), staff=("e3", "e6"))
    week = solve_week(cfg, time_limit_s=10)
    split = [eid for eid in {x.employee_id for x in week.shifts}
             if len([x for x in week.shifts if x.employee_id == eid and x.day == 4]) == 2]
    assert len(split) == 1
    keep = split[0]
    other = next(e.id for e in cfg.employees if e.id != keep)
    req = FixRequest(config=cfg, schedule=week, day=4, now=400,
                     callouts=[CallOut(employee_id=other, day=4, reported_at=400)])
    plan = fix_day(req)
    for sched in (plan.schedule_if_none_accept, plan.schedule_if_all_accept):
        mine = sorted((x.start, x.end) for x in sched.shifts if x.employee_id == keep and x.day == 4)
        assert mine == sorted((x.start, x.end) for x in week.shifts if x.employee_id == keep and x.day == 4)
        assert len({x.id for x in sched.shifts}) == len(sched.shifts)
        assert _hard(cfg, sched) == []


@pytest.fixture(scope="module")
def legal_trap_ca():
    from shiftwright_scenarios import generate
    from shiftwright_validator.audit import with_law_pack

    return with_law_pack(generate(1, "S", "legal_trap", "CA").config)


def test_always_staffed_bound_respects_max_shifts_per_day(legal_trap_ca):
    cfg = legal_trap_ca
    assert cfg.store.max_shifts_per_day == 2
    assert always_staffed_conflict(build_prep(cfg)) is None
    one = cfg.model_copy(update={"store": cfg.store.model_copy(update={"max_shifts_per_day": 1})})
    assert always_staffed_conflict(build_prep(one)) is not None


def test_legal_trap_ca_feasible_with_split_shifts(legal_trap_ca):
    cfg = legal_trap_ca
    s = solve_week(cfg, time_limit_s=30)
    assert s.status in ("optimal", "feasible"), s.infeasibility
    assert _hard(cfg, s) == []
    assert len({x.id for x in s.shifts}) == len(s.shifts)
