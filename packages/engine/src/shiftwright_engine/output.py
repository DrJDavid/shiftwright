"""Turn solver values into contract objects, and compute metrics/gaps exactly from shifts."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ortools.sat.python import cp_model

from shiftwright_contracts.models import (
    AvailabilityKind,
    Gap,
    RoleSegment,
    ScheduleMetrics,
    Shift,
    SoftViolation,
    StoreConfig,
)

from .prep import DAY, SCALE, Prep, _avail_for_day


def shift_id(eid: str, day: int) -> str:
    return f"sh-{eid}-d{day}"


def paid_minutes(sh: Shift) -> int:
    return (sh.end - sh.start) - sum(b.end - b.start for b in sh.breaks if not b.paid)


def shifts_from_solution(built, solver: cp_model.CpSolver) -> list[Shift]:
    p: Prep = built.prep
    out = []
    for c in p.cands:
        v = built.y.get(c.idx)
        if v is None or not solver.boolean_value(v):
            continue
        roles_at = {}
        for a in c.work_slots:
            for r in p.allowed_roles[c.emp]:
                xv = built.x.get((c.emp, r, a))
                if xv is not None and solver.boolean_value(xv):
                    roles_at[a] = r
                    break
        out.append(make_shift(p, c, roles_at))
    return out


def make_shift(p: Prep, c, roles_at: dict[int, str]) -> Shift:
    segs: list[RoleSegment] = []
    base = c.day * DAY
    for a in c.work_slots:
        r = roles_at[a]
        t = a - base
        if segs and segs[-1].role_id == r and segs[-1].end == t:
            segs[-1] = RoleSegment(role_id=r, start=segs[-1].start, end=t + p.slot)
        else:
            segs.append(RoleSegment(role_id=r, start=t, end=t + p.slot))
    return Shift(id=shift_id(c.emp, c.day), employee_id=c.emp, day=c.day, start=c.start, end=c.end,
                 breaks=list(c.breaks), segments=segs)


def coverage_map(p: Prep, shifts: Iterable[Shift]) -> dict[tuple[str, int], int]:
    cov: dict[tuple[str, int], int] = defaultdict(int)
    for sh in shifts:
        for seg in sh.segments:
            t = seg.start
            while t < seg.end:
                cov[(seg.role_id, sh.day * DAY + t)] += 1
                t += p.slot
    return cov


def gaps_from_shifts(p: Prep, shifts: Iterable[Shift]) -> list[Gap]:
    cov = coverage_map(p, shifts)
    roles = {r.id: r for r in p.cfg.roles}
    missing = {}
    for (r, a), dem in p.demand.items():
        miss = dem - min(dem, cov.get((r, a), 0))
        if miss > 0:
            missing[(r, a)] = miss
    gaps: list[Gap] = []
    for (r, a) in sorted(missing, key=lambda k: (k[0], k[1])):
        miss = missing[(r, a)]
        day = min(a // DAY, 6)
        t = a - day * DAY
        pen = (roles[r].gap_penalty_per_hour if r in roles else 0.0) * p.slot / 60 * miss
        last = gaps[-1] if gaps else None
        if last and last.role_id == r and last.day == day and last.end == t and last.missing_headcount == miss:
            last.end = t + p.slot
            last.penalty_dollars = round(last.penalty_dollars + pen, 2)
        else:
            gaps.append(Gap(role_id=r, day=day, start=t, end=t + p.slot, missing_headcount=miss,
                            penalty_dollars=round(pen, 2)))
    return gaps


def availability_violations(p: Prep, shifts: list[Shift]) -> list[SoftViolation]:
    out = []
    by_ed = {(s.employee_id, s.day): s for s in shifts}
    for e in p.cfg.employees:
        for d in range(7):
            sh = by_ed.get((e.id, d))
            for a in _avail_for_day(p, e, d):
                if a.kind == AvailabilityKind.unavailable or a.weight_dollars <= 0:
                    continue
                ov = 0.0
                if sh is not None:
                    ov = max(0, min(sh.end, a.end) - max(sh.start, a.start)) / 60
                hrs = ov if a.kind == AvailabilityKind.preferred_off else (a.end - a.start) / 60 - ov
                if hrs > 0:
                    out.append(SoftViolation(kind="availability_preference", employee_id=e.id, amount=round(hrs, 4),
                                             penalty_dollars=round(hrs * a.weight_dollars, 2),
                                             note=f"{a.kind.value} day {d} {a.start}-{a.end}"))
    return out


def soft_from_solution(built, solver) -> list[SoftViolation]:
    agg: dict[tuple, list[float]] = {}
    for s in built.soft:
        v = solver.value(s.var)
        if v <= 0:
            continue
        key = (s.constraint_id, s.kind, s.employee_id)
        cur = agg.setdefault(key, [0.0, 0.0])
        cur[0] += v * s.amount_per
        cur[1] += v * (s.dollars_per if s.dollars_per is not None else s.units_per / SCALE)
    return [SoftViolation(constraint_id=cid, kind=kind, employee_id=eid, amount=round(a, 4),
                          penalty_dollars=round(d, 2))
            for (cid, kind, eid), (a, d) in agg.items()]


def ot_breakdown(p: Prep, shifts: list[Shift]) -> tuple[float, float]:
    """(overtime_hours, overtime premium dollars): daily OT per shift (law pack daily_overtime), then
    weekly OT over threshold on the remaining hours, so no hour counts twice (WS2 semantics #4)."""
    hours, prem = 0.0, 0.0
    week_min: dict[str, float] = defaultdict(float)  # paid minutes NOT already daily OT
    for sh in shifts:
        e = p.emps[sh.employee_id]
        pm = paid_minutes(sh)
        week_min[e.id] += pm
        if p.daily_ot is not None:
            thr = p.daily_ot.params["threshold_hours"] * 60
            if pm > thr:
                week_min[e.id] -= pm - thr
                hours += (pm - thr) / 60
                prem += (pm - thr) / 60 * e.wage_per_hour * (p.daily_ot.params["multiplier"] - 1)
                dbl = p.daily_ot.params.get("double_threshold_hours")
                if dbl is not None and pm > dbl * 60:
                    prem += (pm - dbl * 60) / 60 * e.wage_per_hour * (2 - p.daily_ot.params["multiplier"])
    if p.weekly_ot is not None:
        thr = p.weekly_ot.params["threshold_hours"] * 60
        for eid, mins in week_min.items():
            if mins > thr:
                hours += (mins - thr) / 60
                prem += (mins - thr) / 60 * p.emps[eid].wage_per_hour * (p.weekly_ot.params["multiplier"] - 1)
    return hours, prem


def compute_metrics(p: Prep, shifts: list[Shift], soft: list[SoftViolation], gaps: list[Gap],
                    premium_pay: float = 0.0) -> ScheduleMetrics:
    cfg: StoreConfig = p.cfg
    total_min = sum(paid_minutes(s) for s in shifts)
    wage = sum(paid_minutes(s) / 60 * p.emps[s.employee_id].wage_per_hour for s in shifts)
    ot_h, ot_prem = ot_breakdown(p, shifts)
    wage += ot_prem
    cov = coverage_map(p, shifts)
    req = sum(p.demand.values())
    got = sum(min(d, cov.get(k, 0)) for k, d in p.demand.items())
    gap_pen = sum(g.penalty_dollars for g in gaps)
    soft_pen = sum(s.penalty_dollars for s in soft)
    cap = cfg.budget.weekly_hours_cap + sum(a.extra_hours for a in cfg.budget.approvals)
    return ScheduleMetrics(
        total_hours=round(total_min / 60, 4),
        total_wage_cost=round(wage, 2),
        overtime_hours=round(ot_h, 4),
        premium_pay_dollars=round(premium_pay, 2),
        coverage_pct=round(100.0 * got / req, 2) if req else 100.0,
        gap_penalty_dollars=round(gap_pen, 2),
        soft_penalty_dollars=round(soft_pen, 2),
        objective_dollars=round(wage + premium_pay + gap_pen + soft_pen, 2),
        budget_hours_cap=cap,
        budget_hours_used=round(total_min / 60, 4),
    )
