"""Coverage first, then cost (SEMANTICS #25, PUNCHLIST C3).

`gap_penalty_per_hour` ranks roles into tiers; the engine never leaves demand uncovered to save
money, and never trades a higher tier's coverage for a lower tier's. Numbers here are arbitrary
test values (wages, penalties, budgets), not law.
"""
from __future__ import annotations

from engine_fixtures import emp, tiny_store, with_law
from shiftwright_contracts.models import (
    AvailabilityEntry,
    AvailabilityKind,
    CallOut,
    DayHours,
    DemandRequirement,
    DemandSource,
    FixRequest,
    Jurisdiction,
    Lever,
)
from shiftwright_engine import fix_day, solve_week
from shiftwright_validator import validate


def _hard(cfg, s):
    return [f"{v.code.value}: {v.message}" for v in validate(cfg, s).violations
            if v.severity == "hard" or v.code.value == "metrics_mismatch"]


def _store(employees, penalties: dict[str, float], demand: list[tuple[str, int, int, int]], hours_cap: float):
    """Friday only, 08:00-16:00, TX. demand = (role, start, end, headcount)."""
    cfg = tiny_store()
    store = cfg.store.model_copy(update={"hours": [DayHours(day=4, open=480, close=960)],
                                         "pre_open_minutes": 0, "post_close_minutes": 0})
    roles = [r.model_copy(update={"gap_penalty_per_hour": penalties[r.id]}) for r in cfg.roles if r.id in penalties]
    dem = [DemandRequirement(id=f"d{i}", role_id=r, day=4, start=a, end=b, headcount=h, source=DemandSource.corporate)
           for i, (r, a, b, h) in enumerate(demand)]
    cfg = cfg.model_copy(update={
        "store": store, "roles": roles, "demand": dem, "employees": employees, "events": [],
        "constraints": [c for c in cfg.constraints if c.id in ("c_min_shift", "c_max_shift")],
        "budget": cfg.budget.model_copy(update={"weekly_hours_cap": hours_cap}),
    })
    return with_law(cfg, Jurisdiction(state="TX", city=None))


def _cheaper(s) -> list:
    return [(g.role_id, r.employee_id) for g in s.gaps for r in g.reasons if r.code.value == "cheaper_to_leave_gap"]


def test_cheap_priority_role_is_covered_when_someone_can():
    """$5/h priority, $20/h wage: the old priced objective left this gap; now it is covered."""
    cfg = _store([emp("e1", ["cashier"], wage=20.0)], {"cashier": 5.0}, [("cashier", 480, 960, 1)], 40)
    s = solve_week(cfg, time_limit_s=10)
    assert s.status in ("optimal", "feasible")
    assert not s.gaps and s.metrics.coverage_pct == 100.0
    assert _hard(cfg, s) == []
    # Reported metrics keep the old formulas: no gap, so no gap penalty; objective = wages + soft.
    assert s.metrics.gap_penalty_dollars == 0.0
    assert s.metrics.objective_dollars == round(s.metrics.total_wage_cost + s.metrics.premium_pay_dollars
                                                + s.metrics.soft_penalty_dollars, 2)


def test_higher_tier_wins_under_binding_budget_even_when_pricier():
    """Budget fits one 8 h shift. Truck unload ranks above cashier, but its only worker costs $40/h
    (penalty $30/h) while the cashier costs $10/h (penalty $25/h): money alone picked the cashier."""
    cfg = _store([emp("hi", ["truck_unload"], wage=40.0), emp("lo", ["cashier"], wage=10.0)],
                 {"truck_unload": 30.0, "cashier": 25.0},
                 [("truck_unload", 480, 960, 1), ("cashier", 480, 960, 1)], 8)
    s = solve_week(cfg, time_limit_s=10)
    assert [x.employee_id for x in s.shifts] == ["hi"]
    assert {g.role_id for g in s.gaps} == {"cashier"}
    assert _hard(cfg, s) == []
    reasons = {(r.employee_id, r.code.value) for g in s.gaps for r in g.reasons}
    assert reasons == {("lo", "budget_cap")}


def test_shared_worker_takes_the_higher_tier_role():
    """One person, two roles at once: she covers the higher tier, whatever the price gap says."""
    cfg = _store([emp("e1", ["cashier", "truck_unload"], wage=20.0)], {"truck_unload": 2.0, "cashier": 1.0},
                 [("truck_unload", 480, 960, 1), ("cashier", 480, 960, 1)], 40)
    s = solve_week(cfg, time_limit_s=10)
    assert len(s.shifts) == 1
    assert {g.role_id for g in s.shifts[0].segments} == {"truck_unload"}
    assert {g.role_id for g in s.gaps} == {"cashier"}
    assert _cheaper(s) == []


def test_soft_penalties_never_decide_coverage():
    """A $500/h preferred_off is a cost: it picks who works, never whether the hour is covered."""
    off = AvailabilityEntry(weekday=4, start=480, end=960, kind=AvailabilityKind.preferred_off, weight_dollars=500.0)
    e1 = emp("e1", ["cashier"], wage=20.0).model_copy(update={"availability": [off]})
    cfg = _store([e1], {"cashier": 10.0}, [("cashier", 480, 960, 1)], 40)
    s = solve_week(cfg, time_limit_s=10)
    assert not s.gaps
    assert _hard(cfg, s) == []
    # With a second, unbothered worker, cost picks her.
    cfg2 = _store([e1, emp("e2", ["cashier"], wage=25.0)], {"cashier": 10.0}, [("cashier", 480, 960, 1)], 40)
    s2 = solve_week(cfg2, time_limit_s=10)
    assert not s2.gaps and [x.employee_id for x in s2.shifts] == ["e2"]


def test_cost_breaks_coverage_ties():
    """Same coverage either way: the cheaper worker gets the shift."""
    cfg = _store([emp("a", ["cashier"], wage=30.0), emp("b", ["cashier"], wage=12.0)], {"cashier": 5.0},
                 [("cashier", 480, 960, 1)], 40)
    s = solve_week(cfg, time_limit_s=10)
    assert [x.employee_id for x in s.shifts] == ["b"] and not s.gaps


def test_fix_day_calls_in_for_a_cheap_priority_gap():
    """fix_day follows the same order: a $5/h gap left by a call-out is offered to an available
    worker even though the call-in costs more than the gap's price."""
    cfg = _store([emp("a", ["cashier"], wage=20.0), emp("b", ["cashier"], wage=20.0)], {"cashier": 5.0},
                 [("cashier", 480, 960, 1)], 40)
    week = solve_week(cfg, time_limit_s=10)
    assert len(week.shifts) == 1
    out = week.shifts[0].employee_id
    other = "b" if out == "a" else "a"
    req = FixRequest(config=cfg, schedule=week, day=4, now=420,
                     callouts=[CallOut(employee_id=out, day=4, reported_at=420)])
    plan = fix_day(req)
    assert [c.employee_id for c in plan.outreach_queue][:1] == [other]
    assert plan.coverage_after_best_pct == 100.0
    assert not plan.schedule_if_all_accept.gaps
    assert _hard(cfg, plan.schedule_if_all_accept) == []


def test_fix_day_extends_for_a_cheap_priority_gap():
    """Without call-ins, an extension (coverage) beats leaving the gap, even at a $1/h priority."""
    busy = AvailabilityEntry(weekday=4, start=720, end=960, kind=AvailabilityKind.unavailable)
    a = emp("a", ["cashier"], wage=10.0).model_copy(update={"availability": [busy]})
    cfg = _store([a, emp("b", ["cashier"], wage=20.0)], {"cashier": 1.0}, [("cashier", 480, 960, 1)], 40)
    week = solve_week(cfg, time_limit_s=10)
    assert not week.gaps and sorted((x.employee_id, x.start, x.end) for x in week.shifts) == [
        ("a", 480, 720), ("b", 720, 960)]
    req = FixRequest(config=cfg, schedule=week, day=4, now=420, allowed_levers=[Lever.reassign, Lever.extend,
                                                                                Lever.drop_coverage],
                     callouts=[CallOut(employee_id="a", day=4, reported_at=420)])
    plan = fix_day(req)
    none = plan.schedule_if_none_accept
    assert _hard(cfg, none) == []
    assert not none.gaps and none.metrics.coverage_pct == 100.0
    assert any(a.lever == Lever.extend for a in plan.actions)


def test_extension_that_only_adds_an_unpaid_meal_is_a_law_reason():
    """CA: 08:00-13:00 is 5 paid hours; reaching 13:30 owes a 30 min unpaid meal, so the longer shift
    adds no paid time and no worked time. The gap is the meal rule's, not 'cheaper to leave'."""
    from shiftwright_contracts.models import Break, RoleSegment, Schedule, Shift
    from shiftwright_engine.explain import explain_with_prep
    from shiftwright_engine.output import gaps_from_shifts
    from shiftwright_engine.prep import build_prep

    cfg = _store([emp("e1", ["cashier"], wage=20.0)], {"cashier": 30.0}, [("cashier", 480, 810, 1)], 5)
    cfg = with_law(cfg, Jurisdiction(state="CA", city=None))
    p = build_prep(cfg)
    sh = Shift(id="s1", employee_id="e1", day=4, start=480, end=780,
               breaks=[Break(start=630, end=640, kind="rest", paid=True)],
               segments=[RoleSegment(role_id="cashier", start=480, end=630),
                         RoleSegment(role_id="cashier", start=640, end=780)])
    gaps = gaps_from_shifts(p, [sh])
    sched = Schedule(store_id=cfg.store.id, week_start=cfg.store.week_start, config_version=cfg.config_version,
                     produced_by="test", status="feasible", shifts=[sh], gaps=gaps)
    tail = next(g for g in gaps if g.start == 780)
    reasons = [(r.employee_id, r.code.value, r.law_rule_id) for r in explain_with_prep(p, sched, tail)]
    assert reasons == [("e1", "law_rule", "CA.meal_break.1")]
