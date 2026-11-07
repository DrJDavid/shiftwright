"""Check the demo store against a real engine schedule (SPEC §7, Saturday 06:04).

    uv run python -m shiftwright_scenarios.verify_demo [time_limit_s] [locality|all]

Checks (per demo store: austin, chicago, seattle, sf, restaurant):
  1. solve_week returns a schedule (optimal/feasible), and WS2's validator finds 0 hard violations.
  2. Each demo call-out (expected.demo.callout_employee_ids) has a Saturday shift still running
     at 06:04 that starts by 12:00 ("Saturday morning").
  3. The repair is possible but not trivial:
     - the call-outs leave real work behind (headcount-hours after 06:04, by role);
     - several plausible call-in candidates exist: adult non-leaders trained (and old enough) for a
       called-out role, with no Saturday shift, free Saturday morning, under max days and max hours,
       and a decent call-in record (offered >= 2, (accepted+1)/(offered+2) >= 0.5).
     With fix_day, also the engine's plan (actions, outreach queue, coverage before/after).
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
from .fixtures import DEMO_STORES, load_demo_scenario

MORNING_END = 12 * 60
MIN_PLAUSIBLE = 3        # "several" call-in candidates
DECENT_PROB = 0.5
CALL_IN_HOURS = 4        # min shift length in the demo store


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


def _paid_hours(s) -> float:
    return (s.end - s.start - sum(b.end - b.start for b in s.breaks if not b.paid)) / 60


def callin_candidates(cfg: StoreConfig, sched: Schedule, callout_ids: list[str], day: int = SATURDAY,
                      now: int = DEFAULT_REPORTED_AT, window_end: int = MORNING_END) -> list[dict]:
    """Everyone who could be called in for a called-out role, best call-in record first."""
    roles = sorted({g.role_id for s in sched.shifts if s.employee_id in callout_ids and s.day == day
                    for g in s.segments if g.end > now})
    min_age = {r.id: r.min_age for r in cfg.roles}
    max_days = min((c.params.get("days", 7) for c in cfg.constraints
                    if c.kind == ConstraintKind.max_days_per_week and c.strength.value == "hard"), default=7)
    working_today = {s.employee_id for s in sched.shifts if s.day == day}
    days = {e.id: len({s.day for s in sched.shifts if s.employee_id == e.id}) for e in cfg.employees}
    hours = {e.id: sum(_paid_hours(s) for s in sched.shifts if s.employee_id == e.id) for e in cfg.employees}

    out: list[dict] = []
    for e in cfg.employees:
        if e.home_department_id == "leadership" or e.id in working_today or e.id in callout_ids:
            continue
        can = [r for r in roles if r in e.trained_role_ids and e.age >= min_age.get(r, 0)]
        if not can or days[e.id] >= max_days or hours[e.id] + CALL_IN_HOURS > e.max_hours_week:
            continue
        if any(a.kind == AvailabilityKind.unavailable and a.weekday == day and a.start < window_end
               and now < a.end for a in e.availability):
            continue
        a = e.attendance
        out.append({"employee_id": e.id, "roles": can, "offered": a.callins_offered_90d,
                    "accepted": a.callins_accepted_90d, "est_accept_prob": round(est_accept_prob(e), 3),
                    "wage": e.wage_per_hour, "hours_scheduled": hours[e.id]})
    out.sort(key=lambda c: (-c["est_accept_prob"], c["wage"], c["employee_id"]))
    return out


def verify(time_limit_s: float = 30, solve_week: Optional[Callable] = None,
           fix_day: Optional[Callable] = None, schedule: Optional[Schedule] = None,
           locality: str = "austin") -> dict[str, Any]:
    sc = load_demo_scenario(locality)
    cfg = with_law_pack(sc.config)
    demo = sc.expected["demo"]
    callout_ids: list[str] = demo["callout_employee_ids"]
    day: int = sc.expected.get("callout_day", SATURDAY)
    now: int = sc.expected.get("callout_reported_at", DEFAULT_REPORTED_AT)
    # Retail: a 06:04 call-out for a Saturday-morning shift. Later call-outs (restaurant 15:30): any
    # shift that day that hasn't ended.
    window_end = MORNING_END if now < MORNING_END else 24 * 60
    if schedule is None:
        if solve_week is None:
            solve_week, fix_day = engine_functions()
        if solve_week is None:
            raise RuntimeError("shiftwright_engine.solve_week not available")
        schedule = solve_week(cfg, time_limit_s=time_limit_s)
    rep: dict[str, Any] = {"locality": locality, "status": getattr(schedule.status, "value", schedule.status)}
    if schedule.metrics is not None:
        rep["metrics"] = schedule.metrics.model_dump(include={"coverage_pct", "total_hours", "total_wage_cost",
                                                              "premium_pay_dollars", "gap_penalty_dollars"})
    try:
        from shiftwright_validator import validate
    except ImportError:
        rep["validator"] = None
    else:
        vr = validate(cfg, schedule)
        rep["validator"] = {"passed": vr.passed, "hard_count": vr.hard_count,
                            "hard": [f"{v.code.value}: {v.message}" for v in vr.violations
                                     if getattr(v.severity, "value", v.severity) == "hard"][:10]}

    morning: dict[str, Any] = {}
    lost: dict[str, float] = {}
    for eid in callout_ids:
        shifts = [s for s in schedule.shifts if s.employee_id == eid and s.day == day]
        ok = [s for s in shifts if s.end > now and s.start < window_end]
        morning[eid] = {"scheduled_morning": bool(ok),
                        "shifts": [(s.start, s.end, sorted({g.role_id for g in s.segments})) for s in shifts]}
        for s in ok:
            for g in s.segments:
                h = (g.end - max(g.start, now)) / 60
                if h > 0:
                    lost[g.role_id] = lost.get(g.role_id, 0) + h
    rep["callouts"] = morning
    rep["callouts_ok"] = all(v["scheduled_morning"] for v in morning.values())
    rep["lost_hours_by_role"] = {r: round(h, 2) for r, h in sorted(lost.items())}
    if not rep["callouts_ok"]:
        keep_out = {demo[k] for k in ("jordan_id", "casey_id", "minor_pit_id", "minor_fryer_id") if k in demo}
        trimmed = schedule.model_copy(update={"shifts": [s for s in schedule.shifts if s.employee_id not in keep_out]})
        rep["repick"] = [c.employee_id for c in pick_callouts(cfg, trimmed, day, n=len(callout_ids),
                                                               now=now, seed=417)]

    cands = callin_candidates(cfg, schedule, callout_ids, day, now, window_end)
    plausible = [c for c in cands if c["offered"] >= 2 and c["est_accept_prob"] >= DECENT_PROB]
    rep["callin_candidates"] = len(cands)
    rep["plausible_callins"] = plausible[:8]
    rep["repair_not_trivial"] = sum(lost.values()) >= CALL_IN_HOURS
    rep["repair_possible"] = len(plausible) >= MIN_PLAUSIBLE

    if fix_day is not None:
        from shiftwright_contracts.models import FixRequest

        callouts = [CallOut(employee_id=eid, day=day, reported_at=now) for eid in callout_ids]
        plan = fix_day(FixRequest(config=cfg, schedule=schedule, callouts=callouts, day=day, now=now))
        rep["fix"] = {"actions": [(a.lever.value, a.employee_id, a.role_id) for a in plan.actions],
                      "outreach_queue": [(c.employee_id, c.est_accept_prob)
                                         for c in sorted(plan.outreach_queue, key=lambda c: c.rank)],
                      "coverage_before_pct": plan.coverage_before_pct,
                      "coverage_after_best_pct": plan.coverage_after_best_pct,
                      "coverage_after_worst_pct": plan.coverage_after_worst_pct}
    return rep


if __name__ == "__main__":
    t = float(sys.argv[1]) if len(sys.argv) > 1 else 30
    which = sys.argv[2] if len(sys.argv) > 2 else "austin"
    for loc in (DEMO_STORES if which == "all" else (which,)):
        print(json.dumps(verify(t, locality=loc), indent=2, default=str))
