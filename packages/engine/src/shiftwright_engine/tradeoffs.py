"""Tradeoffs for the manager (SEMANTICS #25): what keeping a rule or the budget really costs.

After the main solve, up to `MAX_SOLVES` short what-if solves, each from an actual CP-SAT run on a
neighbourhood of the final week (never estimated):
  - budget_gap: a gap left open because of the hours budget. The gap's day is re-solved for
    everyone trained for the role with the budget raised by the gap's hours (at least one minimum
    shift); recorded only if that gap gets (partly) covered and coverage rises.
  - preference_cost: a soft rule the week keeps. The week of the employees it names is re-solved
    (coworkers sharing a role may drop their current shifts) with the rule and without it (both runs, so solver slack doesn't count as savings); recorded
    only if dropping it really lowers wage cost.
`if_kept` is the week with the budget / rule as it is, `if_dropped` the what-if. Numbers are the
reported metrics (wage cost, paid hours, coverage %) of each schedule, same formulas as always.
"""
from __future__ import annotations

import copy
import math
import time

from ortools.sat.python import cp_model
from shiftwright_contracts.models import ConstraintKind, GapReasonCode, Schedule, Strength

from .lex import role_tier
from .model import Builder, solve
from .output import (
    availability_violations,
    compute_metrics,
    gaps_from_shifts,
    shifts_from_solution,
    soft_from_solution,
)
from .prep import Prep

MAX_SOLVES = 5
MAX_ITEMS = 5


def _numbers(m) -> dict:
    return {"wage_cost": m.total_wage_cost, "hours": m.total_hours, "coverage_pct": m.coverage_pct}


def _run(p: Prep, chosen: set[int], roles: dict, free_emps: set[str], days: set[int] | None,
         limit_s: float, extra_cap: int = 0, droppable: frozenset[str] = frozenset()):
    """Re-solve the week with `free_emps`' shifts (on `days`, or all week) open and `droppable`
    employees' current shifts optional; every other shift kept. Returns (metrics, gaps) or None."""
    def free(c) -> bool:
        return c.emp in free_emps and (days is None or c.day in days)
    forced = {i for i in chosen if not free(p.cands[i]) and p.cands[i].emp not in droppable}
    b = Builder(p, cand_ok=lambda c: c.idx in chosen or free(c), forced=forced, churn=True,
                extra_cap_minutes=extra_cap).build()
    hint = {v: int(i in chosen) for i, v in b.y.items()}
    for (e, r, a), v in b.x.items():
        hint[v] = int(roles.get((e, a)) == r)
    s, st = solve(b, limit_s, hint=hint, mode="lex")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    shifts = shifts_from_solution(b, s)
    soft = soft_from_solution(b, s) + availability_violations(p, shifts)
    gaps = gaps_from_shifts(p, shifts)
    return compute_metrics(p, shifts, soft, gaps), gaps


def _missing(gaps, role_id: str, day: int, start: int, end: int) -> int:
    """Missing headcount-minutes of `role_id` inside [start, end) on `day`."""
    return sum(g.missing_headcount * (min(g.end, end) - max(g.start, start)) for g in gaps
               if g.role_id == role_id and g.day == day and g.start < end and start < g.end)


def tradeoffs(p: Prep, sched: Schedule, chosen: set[int], roles: dict, limit_s: float,
              until: float | None = None) -> list[dict]:
    if sched.metrics is None:
        return []
    base = _numbers(sched.metrics)
    tier = role_tier(p)
    out: list[dict] = []
    solves = 0

    def time_ok() -> bool:
        return solves < MAX_SOLVES and (until is None or time.perf_counter() + limit_s <= until)

    # Budget gaps: biggest tier × missing headcount-hours first, one per role-day.
    cands = [g for g in sched.gaps if any(r.code == GapReasonCode.budget_cap for r in g.reasons)]
    cands.sort(key=lambda g: (-tier.get(g.role_id, 0), -g.missing_headcount * (g.end - g.start)))
    seen = set()
    for g in cands:
        if (g.role_id, g.day) in seen or not time_ok():
            continue
        seen.add((g.role_id, g.day))
        trained = {e.id for e in p.cfg.employees if g.role_id in e.trained_role_ids}
        lo = min((p.shift_bounds(e)[0] for e in trained), default=60)
        need = max(g.missing_headcount * (g.end - g.start), lo)
        extra = int(math.ceil(need / 60) * 60)
        solves += 1
        res = _run(p, chosen, roles, trained, {g.day}, limit_s, extra_cap=extra)
        if res is None:
            continue
        m, gaps = res
        if (m.coverage_pct <= base["coverage_pct"]
                or _missing(gaps, g.role_id, g.day, g.start, g.end) >= g.missing_headcount * (g.end - g.start)):
            continue
        out.append({"id": f"budget_gap:{g.role_id}:{g.day}:{g.start}", "kind": "budget_gap",
                    "role_id": g.role_id, "day": g.day, "window": [g.start, g.end],
                    "extra_hours": round(m.total_hours - base["hours"], 2),
                    "if_kept": dict(base), "if_dropped": _numbers(m)})
        if len(out) >= 3:
            break

    # Preferences kept: soft rules with no violation, naming at most 3 employees.
    broken = {v.constraint_id for v in sched.soft_violations}
    for con in sorted(p.constraints, key=lambda c: -c.weight_dollars):
        if MAX_SOLVES - solves < 2 or not time_ok():
            break
        if con.strength != Strength.soft or con.id in broken or con.kind == ConstraintKind.always_staffed:
            continue
        ids = con.applies_to_employee_ids or [con.params[k] for k in ("employee_id",) if con.params.get(k)] \
            or list(con.params.get("employee_ids", []))
        emps = {e for e in ids if e in p.emps}
        if not emps or len(emps) > 3:
            continue
        mates = frozenset(e.id for e in p.cfg.employees if e.id not in emps and any(
            r in p.allowed_roles.get(e.id, []) for x in emps for r in p.allowed_roles.get(x, [])))
        p2 = copy.copy(p)
        p2.constraints = [c for c in p.constraints if c.id != con.id]
        solves += 2
        kept = _run(p, chosen, roles, emps, None, limit_s, droppable=mates)
        dropped = _run(p2, chosen, roles, emps, None, limit_s, droppable=mates)
        if kept is None or dropped is None:
            continue
        kept, dropped = kept[0], dropped[0]
        if dropped.coverage_pct < kept.coverage_pct or kept.total_wage_cost - dropped.total_wage_cost < 1.0:
            continue
        out.append({"id": f"preference_cost:{con.id}", "kind": "preference_cost", "rule_id": con.id,
                    "day": None, "if_kept": _numbers(kept), "if_dropped": _numbers(dropped)})

    def size(t) -> float:
        return abs(t["if_kept"]["wage_cost"] - t["if_dropped"]["wage_cost"])
    return sorted(out, key=size, reverse=True)[:MAX_ITEMS]


__all__ = ["tradeoffs", "MAX_SOLVES"]
