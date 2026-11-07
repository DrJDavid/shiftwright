"""Past weeks of schedules, built by a simple greedy "how a store leader would have done it" pass.

Not optimal and not meant to be: it gives the insights miner real patterns (who works with whom,
how many cashiers after 17:00) and gives week_stability a previous week. Respects training,
min_age, unavailable windows, max hours, one shift per day, 5 days max and not_together pairs.
Breaks are not modeled (corporate exports rarely carry them). metrics are left None rather than
claiming numbers nobody checked.
"""
from __future__ import annotations

import random
from datetime import timedelta

from shiftwright_contracts.models import (
    AvailabilityKind,
    ConstraintKind,
    RoleSegment,
    Schedule,
    Shift,
    StoreConfig,
)

# (role_id, from_hour, to_hour, min_headcount) applied on top of demand, e.g. a leader habit.
Floor = tuple[str, int, int, int]


def _hourly_from_demand(cfg: StoreConfig) -> dict[tuple[str, int], list[int]]:
    prof: dict[tuple[str, int], list[int]] = {}
    for d in cfg.demand:
        row = prof.setdefault((d.role_id, d.day), [0] * 24)
        for h in range(d.start // 60, -(-d.end // 60)):
            row[h] = max(row[h], d.headcount)
    return prof


def build_history(
    rng: random.Random, cfg: StoreConfig, weeks: int = 8, floors: list[Floor] | None = None
) -> list[Schedule]:
    base = _hourly_from_demand(cfg)
    for role, h0, h1, n in floors or []:
        for day in range(7):
            row = base.setdefault((role, day), [0] * 24)
            for h in range(h0, h1):
                row[h] = max(row[h], n)
    penalty = {r.id: r.gap_penalty_per_hour for r in cfg.roles}
    min_age = {r.id: r.min_age for r in cfg.roles}
    emps = cfg.employees
    pairs: list[tuple[str, str]] = []
    for c in cfg.constraints:
        if c.kind == ConstraintKind.not_together:
            a, b = c.params["employee_ids"][:2]
            pairs.append((a, b))
    partner: dict[str, list[str]] = {}
    for a, b in pairs:
        partner.setdefault(a, []).append(b)
        partner.setdefault(b, []).append(a)
    blocked = {
        e.id: [(a.weekday, a.start, a.end) for a in e.availability
               if a.kind == AvailabilityKind.unavailable and a.weekday is not None]
        for e in emps
    }
    floor_hours = {(role, day): set(range(h0, h1)) for role, h0, h1, _ in floors or [] for day in range(7)}

    out: list[Schedule] = []
    for k in range(weeks, 0, -1):
        hours_used = {e.id: 0.0 for e in emps}
        days_used = {e.id: 0 for e in emps}
        shifts: list[Shift] = []
        for day in range(7):
            dh = next((x for x in cfg.store.hours if x.day == day), None)
            if dh is None:
                continue
            lo = (dh.open - cfg.store.pre_open_minutes) // 60
            hi = (dh.close + cfg.store.post_close_minutes) // 60
            today: dict[str, tuple[int, int]] = {}
            keys = sorted((key for key in base if key[1] == day), key=lambda key: (-penalty[key[0]], key[0]))
            for role, _ in keys:
                need = list(base[(role, day)])
                for h in range(24):  # week-to-week noise, but never below a leader habit floor
                    if need[h] > 1 and h not in floor_hours.get((role, day), ()) and rng.random() < 0.1:
                        need[h] -= 1
                hrs = [h for h in range(24) if need[h] > 0]
                w0, w1 = hrs[0], hrs[-1] + 1
                cov = [0] * 24
                for h in range(w0, w1):
                    while cov[h] < need[h]:
                        length = rng.choice([4, 5, 6, 8])
                        end = min(h + length, w1)
                        if end - h < 4:
                            end = min(h + 4, hi)
                        start = max(lo, min(h, end - 4))
                        s_min, e_min = start * 60, end * 60
                        cands = []
                        for e in emps:
                            if (e.id in today or role not in e.trained_role_ids or e.age < min_age[role]
                                    or days_used[e.id] >= 5
                                    or hours_used[e.id] + (end - start) > e.max_hours_week):
                                continue
                            if any(wd == day and s_min < be and bs < e_min for wd, bs, be in blocked[e.id]):
                                continue
                            if any(p in today and today[p][0] < e_min and s_min < today[p][1]
                                   for p in partner.get(e.id, [])):
                                continue
                            cands.append(e)
                        if not cands:
                            break  # a gap in history, like real life
                        pick = min(cands, key=lambda e: hours_used[e.id] + rng.random() * 8)
                        today[pick.id] = (s_min, e_min)
                        hours_used[pick.id] += end - start
                        days_used[pick.id] += 1
                        shifts.append(Shift(
                            id=f"h{k}_{len(shifts) + 1}", employee_id=pick.id, day=day, start=s_min, end=e_min,
                            segments=[RoleSegment(role_id=role, start=s_min, end=e_min)],
                        ))
                        for x in range(start, end):
                            cov[x] += 1
        out.append(Schedule(
            store_id=cfg.store.id,
            week_start=cfg.store.week_start - timedelta(days=7 * k),
            config_version=cfg.config_version,
            produced_by="history",
            status="feasible",
            shifts=shifts,
        ))
    return out
