"""Check the demo store against a real engine schedule (SPEC §7, Saturday 06:04).

    uv run python -m shiftwright_scenarios.verify_demo [time_limit_s]

Checks:
  1. solve_week returns a schedule (optimal/feasible).
  2. Each demo call-out (expected.demo.callout_employee_ids) has a Saturday shift still running
     at 06:04 that starts by 12:00 ("Saturday morning").
  3. The demo phones (expected.demo.demo_phone_employee_ids) rank 1-2 for outreach. With
     fix_day: the engine's outreach_queue. Without it: a proxy from config + schedule only,
     ranking every callable employee (adult non-leader, trained in a called-out role, no
     Saturday shift, free Saturday morning, under max days and max hours) by
     est_accept_prob = (accepted+1)/(offered+2), then wage.
If a call-out misses, `repick` suggests replacements via pick_callouts() (demo people excluded).
"""
from __future__ import annotations

import importlib
import json
import sys
from typing import Any, Callable, Optional

from shiftwright_contracts.models import (
    AvailabilityKind,
    CallOut,
    ConstraintKind,
    Schedule,
    StoreConfig,
)

from .callouts import DEFAULT_REPORTED_AT, pick_callouts
from .demo import SATURDAY
from .fixtures import load_demo_scenario

MORNING_END = 12 * 60


def engine_functions() -> tuple[Optional[Callable], Optional[Callable]]:
    try:
        engine = importlib.import_module("shiftwright_engine")
    except ImportError:
        return None, None
    return getattr(engine, "solve_week", None), getattr(engine, "fix_day", None)


def with_law_pack(cfg: StoreConfig) -> StoreConfig:
    from shiftwright_laws import resolve

    out = cfg.model_copy(deep=True)
    out.law_pack = resolve(cfg.store.jurisdiction, on=cfg.store.week_start)
    return out


def est_accept_prob(e) -> float:
    a = e.attendance
    return (a.callins_accepted_90d + 1) / (a.callins_offered_90d + 2)


def proxy_outreach_ranking(cfg: StoreConfig, sched: Schedule, callout_ids: list[str], day: int = SATURDAY,
                           now: int = DEFAULT_REPORTED_AT) -> list[str]:
    roles = sorted({g.role_id for s in sched.shifts if s.employee_id in callout_ids and s.day == day
                    for g in s.segments if g.end > now})
    min_age = {r.id: r.min_age for r in cfg.roles}
    max_days = min((c.params.get("days", 7) for c in cfg.constraints
                    if c.kind == ConstraintKind.max_days_per_week and c.strength.value == "hard"), default=7)
    working_today = {s.employee_id for s in sched.shifts if s.day == day}
    days = {e.id: len({s.day for s in sched.shifts if s.employee_id == e.id}) for e in cfg.employees}
    hours = {e.id: sum((s.end - s.start - sum(b.end - b.start for b in s.breaks if not b.paid)) / 60
                       for s in sched.shifts if s.employee_id == e.id) for e in cfg.employees}

    def callable_(e) -> bool:
        if e.home_department_id == "leadership" or e.id in working_today or e.id in callout_ids:
            return False
        if not any(r in e.trained_role_ids and e.age >= min_age.get(r, 0) for r in roles):
            return False
        if days[e.id] >= max_days or hours[e.id] + 4 > e.max_hours_week:
            return False
        return not any(a.kind == AvailabilityKind.unavailable and a.weekday == day and a.start < MORNING_END
                       and now < a.end for a in e.availability)

    cands = [e for e in cfg.employees if callable_(e)]
    cands.sort(key=lambda e: (-est_accept_prob(e), e.wage_per_hour, e.id))
    return [e.id for e in cands]


def verify(time_limit_s: float = 30, solve_week: Optional[Callable] = None,
           fix_day: Optional[Callable] = None, schedule: Optional[Schedule] = None) -> dict[str, Any]:
    sc = load_demo_scenario()
    cfg = with_law_pack(sc.config)
    demo = sc.expected["demo"]
    callout_ids: list[str] = demo["callout_employee_ids"]
    phones: list[str] = demo["demo_phone_employee_ids"]
    if schedule is None:
        if solve_week is None:
            solve_week, fix_day = engine_functions()
        if solve_week is None:
            raise RuntimeError("shiftwright_engine.solve_week not available")
        schedule = solve_week(cfg, time_limit_s=time_limit_s)
    rep: dict[str, Any] = {"status": schedule.status.value if hasattr(schedule.status, "value") else schedule.status}
    if schedule.metrics is not None:
        rep["metrics"] = schedule.metrics.model_dump(include={"coverage_pct", "total_hours", "total_wage_cost",
                                                              "gap_penalty_dollars"})

    morning: dict[str, Any] = {}
    for eid in callout_ids:
        shifts = [s for s in schedule.shifts if s.employee_id == eid and s.day == SATURDAY]
        ok = [s for s in shifts if s.end > DEFAULT_REPORTED_AT and s.start < MORNING_END]
        morning[eid] = {"scheduled_morning": bool(ok),
                        "shifts": [(s.start, s.end, sorted({g.role_id for g in s.segments})) for s in shifts]}
    rep["callouts"] = morning
    rep["callouts_ok"] = all(v["scheduled_morning"] for v in morning.values())
    if not rep["callouts_ok"]:
        keep_out = set(phones) | {demo["jordan_id"], demo["casey_id"], demo["minor_pit_id"]}
        repick = pick_callouts(cfg, schedule.model_copy(update={"shifts": [
            s for s in schedule.shifts if s.employee_id not in keep_out]}), SATURDAY, n=3,
            now=DEFAULT_REPORTED_AT, seed=417)
        rep["repick"] = [c.employee_id for c in repick]

    rep["demo_phones_scheduled_saturday"] = sorted({s.employee_id for s in schedule.shifts
                                                    if s.day == SATURDAY and s.employee_id in phones})
    proxy = proxy_outreach_ranking(cfg, schedule, callout_ids)
    rep["proxy_ranking_top5"] = [(eid, round(est_accept_prob(next(e for e in cfg.employees if e.id == eid)), 3))
                                 for eid in proxy[:5]]
    rep["proxy_phones_ok"] = proxy[:2] == phones or set(proxy[:2]) == set(phones)

    if fix_day is not None:
        from shiftwright_contracts.models import FixRequest

        callouts = [CallOut(employee_id=eid, day=SATURDAY, reported_at=DEFAULT_REPORTED_AT) for eid in callout_ids]
        plan = fix_day(FixRequest(config=cfg, schedule=schedule, callouts=callouts, day=SATURDAY,
                                  now=DEFAULT_REPORTED_AT))
        queue = [c.employee_id for c in sorted(plan.outreach_queue, key=lambda c: c.rank)]
        rep["fix"] = {"actions": [(a.lever.value, a.employee_id, a.role_id) for a in plan.actions],
                      "outreach_queue": queue,
                      "coverage_before_pct": plan.coverage_before_pct,
                      "coverage_after_best_pct": plan.coverage_after_best_pct,
                      "coverage_after_worst_pct": plan.coverage_after_worst_pct}
        rep["fix_phones_ok"] = set(queue[:2]) == set(phones)
    return rep


if __name__ == "__main__":
    print(json.dumps(verify(float(sys.argv[1]) if len(sys.argv) > 1 else 30), indent=2, default=str))
