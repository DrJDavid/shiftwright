"""fix_day acceptance tests (briefs/WS1-engine.md "Fixer", SEMANTICS #16)."""
from __future__ import annotations

import time

import pytest
from engine_fixtures import tiny_store
from shiftwright_contracts.models import CallOut, FixRequest, Lever, Schedule, Shift
from shiftwright_engine import fix_day, solve_week
from shiftwright_validator import validate

DAY = 1440


def _hard(cfg, s: Schedule, callouts=()):
    """Hard problems, except a called-out employee's already-worked stub being under the minimum
    shift length (kept on purpose: it already happened)."""
    return [v.message for v in validate(cfg, s).violations if (v.severity == "hard" or v.code.value == "metrics_mismatch")
            and not (v.code.value == "shift_length" and v.employee_id in set(callouts))]


def ids_of(req):
    return [c.employee_id for c in req.callouts]


def _before(sh: Shift, now: int):
    """The part of a shift that lies before `now` (start, breaks and role minutes)."""
    segs = [(g.role_id, g.start, min(g.end, now)) for g in sh.segments if g.start < now]
    return sh.start if sh.start < now else None, segs, [(b.start, b.end) for b in sh.breaks if b.start < now]


def _check_frozen(week: Schedule, plan, req: FixRequest):
    out = {(s.employee_id, s.day): s for s in week.shifts}
    for sched in (plan.schedule_if_all_accept, plan.schedule_if_none_accept):
        got = {(s.employee_id, s.day): s for s in sched.shifts}
        callouts = {c.employee_id for c in req.callouts}
        for k, o in out.items():
            eid, d = k
            if d != req.day:
                assert k in got and got[k].model_dump(exclude={"why"}) == o.model_dump(exclude={"why"}), k
            elif eid not in callouts and o.start < req.now:
                assert k in got and _before(got[k], req.now) == _before(o, req.now), k
        for k, s in got.items():
            if k not in out:  # call-in
                assert s.day == req.day and s.start >= req.now


def _first_shift_today(week: Schedule, day: int, now: int):
    """Shifts not started by `now`, cashier shifts first (others can cover cashier)."""
    return sorted((s for s in week.shifts if s.day == day and s.start >= now),
                  key=lambda s: ("cashier" not in {g.role_id for g in s.segments}, s.start))


@pytest.fixture(scope="module")
def tiny_week():
    cfg = tiny_store()
    return cfg, solve_week(cfg, time_limit_s=10)


def test_tiny_callout_fix(tiny_week):
    cfg, week = tiny_week
    day, now = 5, 6 * 60
    victim = _first_shift_today(week, day, now)[0]
    req = FixRequest(config=cfg, schedule=week, day=day, now=now,
                     callouts=[CallOut(employee_id=victim.employee_id, day=day, reported_at=now)])
    t0 = time.perf_counter()
    plan = fix_day(req)
    assert time.perf_counter() - t0 < 10
    assert _hard(cfg, plan.schedule_if_all_accept, ids_of(req)) == []
    assert _hard(cfg, plan.schedule_if_none_accept, ids_of(req)) == []
    assert not any(s.employee_id == victim.employee_id and s.day == day
                   for s in plan.schedule_if_none_accept.shifts)
    _check_frozen(week, plan, req)
    assert plan.coverage_after_best_pct >= plan.coverage_after_worst_pct >= plan.coverage_before_pct - 1e-9
    assert [c.rank for c in plan.outreach_queue] == list(range(1, len(plan.outreach_queue) + 1))
    for c in plan.outreach_queue:
        assert c.employee_id != victim.employee_id
        assert c.proposed_shift.day == day and c.proposed_shift.start >= now
        e = next(e for e in cfg.employees if e.id == c.employee_id)
        a = e.attendance
        assert c.est_accept_prob == pytest.approx((a.callins_accepted_90d + 1) / (a.callins_offered_90d + 2), abs=1e-4)


def test_declined_and_disallowed_levers(tiny_week):
    cfg, week = tiny_week
    day, now = 5, 6 * 60
    victim = _first_shift_today(week, day, now)[0]
    callouts = [CallOut(employee_id=victim.employee_id, day=day, reported_at=now)]
    plan = fix_day(FixRequest(config=cfg, schedule=week, day=day, now=now, callouts=callouts))
    declined = [c.employee_id for c in plan.outreach_queue]
    plan2 = fix_day(FixRequest(config=cfg, schedule=week, day=day, now=now, callouts=callouts,
                               declined_employee_ids=declined))
    assert not set(declined) & {c.employee_id for c in plan2.outreach_queue}
    plan3 = fix_day(FixRequest(config=cfg, schedule=week, day=day, now=now, callouts=callouts,
                               allowed_levers=[Lever.reassign, Lever.drop_coverage]))
    assert plan3.outreach_queue == []
    assert not any(a.lever in (Lever.extend, Lever.call_in) for a in plan3.actions)
    assert _hard(cfg, plan3.schedule_if_none_accept, ()) == []


@pytest.fixture(scope="module")
def demo():
    from shiftwright_scenarios.callouts import DEFAULT_REPORTED_AT
    from shiftwright_scenarios.demo import SATURDAY
    from shiftwright_scenarios.fixtures import load_demo_scenario
    from shiftwright_scenarios.verify_demo import with_law_pack

    sc = load_demo_scenario()
    cfg = with_law_pack(sc.config)
    week = solve_week(cfg, time_limit_s=15)
    ids = sc.expected["demo"]["callout_employee_ids"]
    req = FixRequest(config=cfg, schedule=week, day=SATURDAY, now=DEFAULT_REPORTED_AT,
                     callouts=[CallOut(employee_id=e, day=SATURDAY, reported_at=DEFAULT_REPORTED_AT) for e in ids])
    return cfg, week, req


def test_demo_callout_under_10s(demo):
    cfg, week, req = demo
    t0 = time.perf_counter()
    plan = fix_day(req)
    assert time.perf_counter() - t0 < 10
    assert _hard(cfg, plan.schedule_if_all_accept, ids_of(req)) == []
    assert _hard(cfg, plan.schedule_if_none_accept, ids_of(req)) == []
    _check_frozen(week, plan, req)
    assert _fix_report(req, plan) == []
    assert plan.outreach_queue
    assert plan.coverage_after_best_pct >= plan.coverage_after_worst_pct >= plan.coverage_before_pct - 1e-9
    working = {s.employee_id for s in week.shifts if s.day == req.day}
    for c in plan.outreach_queue:
        assert c.employee_id not in working
        assert c.proposed_shift.day == req.day and c.proposed_shift.start >= req.now
        e = next(e for e in cfg.employees if e.id == c.employee_id)
        a = e.attendance
        assert c.est_accept_prob == pytest.approx((a.callins_accepted_90d + 1) / (a.callins_offered_90d + 2), abs=1e-4)


def test_demo_decline_and_accept(demo):
    """The API appends an accepted proposed shift and calls fix_day again; declines are excluded."""
    cfg, week, req = demo
    plan = fix_day(req)
    top = plan.outreach_queue[0]
    plan_d = fix_day(req.model_copy(update={"declined_employee_ids": [top.employee_id]}))
    assert top.employee_id not in {c.employee_id for c in plan_d.outreach_queue}
    week2 = week.model_copy(update={"shifts": week.shifts + [top.proposed_shift]})
    req2 = req.model_copy(update={"schedule": week2})
    plan2 = fix_day(req2)
    assert top.employee_id not in {c.employee_id for c in plan2.outreach_queue}
    assert any(s.employee_id == top.employee_id and s.day == req.day for s in plan2.schedule_if_none_accept.shifts)
    assert _hard(cfg, plan2.schedule_if_none_accept, ids_of(req2)) == []
    assert _hard(cfg, plan2.schedule_if_all_accept, ids_of(req2)) == []
    _check_frozen(week2, plan2, req2)
    assert _fix_report(req2, plan2) == []


def _fix_report(req, plan):
    from shiftwright_validator import validate_fix
    r = validate_fix(req, plan)
    out = {c.employee_id for c in req.callouts}
    return [f"{v.code.value}: {v.message}" for v in r.violations
            if (v.severity == "hard" or v.code.value == "metrics_mismatch") and v.code.value != "below_minimum_wage"
            and not (v.code.value == "shift_length" and v.employee_id in out)]


def test_callout_after_start_keeps_worked_part(tiny_week):
    cfg, week = tiny_week
    day = 5
    started = sorted((s for s in week.shifts if s.day == day and s.end - s.start >= 300), key=lambda s: s.start)[0]
    now = started.start + 4 * 60 + 10  # 4 h 10 min in: the worked part meets the 4 h minimum
    req = FixRequest(config=cfg, schedule=week, day=day, now=now,
                     callouts=[CallOut(employee_id=started.employee_id, day=day, reported_at=now)])
    plan = fix_day(req)
    for sched in (plan.schedule_if_all_accept, plan.schedule_if_none_accept):
        mine = [s for s in sched.shifts if s.employee_id == started.employee_id and s.day == day]
        assert [(s.start, s.end) for s in mine] == [(started.start, started.start + 4 * 60)]
    notes = [a for a in plan.actions if a.employee_id == started.employee_id]
    assert notes and "already worked" in notes[0].rationale
    assert _fix_report(req, plan) == []


def test_callout_after_start_short_part_is_kept_and_noted(tiny_week):
    cfg, week = tiny_week
    day = 5
    started = sorted((s for s in week.shifts if s.day == day), key=lambda s: s.start)[0]
    now = started.start + 70
    req = FixRequest(config=cfg, schedule=week, day=day, now=now,
                     callouts=[CallOut(employee_id=started.employee_id, day=day, reported_at=now)])
    plan = fix_day(req)
    mine = [s for s in plan.schedule_if_none_accept.shifts if s.employee_id == started.employee_id and s.day == day]
    assert [(s.start, s.end) for s in mine] == [(started.start, started.start + 60)]
    note = next(a for a in plan.actions if a.employee_id == started.employee_id)
    assert "minimum shift" in note.rationale
