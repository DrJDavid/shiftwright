"""Call-out events.

`default_callouts` picks plausible call-outs before any schedule exists (people trained in the
truck-day roles who could be working that morning). Whether they are actually scheduled depends
on the engine, so evals should prefer `pick_callouts(config, schedule, ...)`, which picks from
real shifts in a given schedule, deterministically.
"""
from __future__ import annotations

import random

from shiftwright_contracts.models import AvailabilityKind, CallOut, Employee, Schedule, StoreConfig

DEFAULT_REPORTED_AT = 6 * 60 + 4  # 06:04, as in the demo script


def _free_morning(e: Employee, day: int) -> bool:
    return not any(
        a.kind == AvailabilityKind.unavailable and a.weekday == day and a.start < 14 * 60 and 4 * 60 < a.end
        for a in e.availability
    )


def default_callouts(rng: random.Random, cfg: StoreConfig, day: int, n: int = 3) -> list[CallOut]:
    min_age = {r.id: r.min_age for r in cfg.roles}
    pool = [e for e in cfg.employees if e.home_department_id != "leadership" and _free_morning(e, day)]
    picked: list[str] = []
    for role in ["truck_unload", "pit_operator", "cashier", "guest_service_desk", "drive_up"]:
        if len(picked) >= n:
            break
        cands = [e.id for e in pool if role in e.trained_role_ids and e.age >= min_age.get(role, 0)
                 and e.id not in picked]
        if cands:
            picked.append(rng.choice(cands))
    return [CallOut(employee_id=eid, day=day, reported_at=DEFAULT_REPORTED_AT) for eid in picked]


def pick_callouts(
    cfg: StoreConfig, schedule: Schedule, day: int, n: int = 3, now: int = DEFAULT_REPORTED_AT, seed: int = 0,
    include_leaders: bool = False,
) -> list[CallOut]:
    """Pick `n` employees with shifts on `day` that haven't ended by `now`, favoring high-priority roles."""
    rng = random.Random(f"pick_callouts|{seed}|{day}|{n}|{now}")
    penalty = {r.id: r.gap_penalty_per_hour for r in cfg.roles}
    shifts = sorted((s for s in schedule.shifts if s.day == day and s.end > now and s.segments
                     and (include_leaders or all(g.role_id != "leader_on_duty" for g in s.segments))),
                    key=lambda s: (s.employee_id, s.start))
    scored = [(max(penalty.get(g.role_id, 0) for g in s.segments) + rng.random(), s.employee_id) for s in shifts]
    scored.sort(reverse=True)
    seen: list[str] = []
    for _, eid in scored:
        if eid not in seen:
            seen.append(eid)
    top = seen[: 2 * n]
    rng.shuffle(top)
    return [CallOut(employee_id=eid, day=day, reported_at=now) for eid in top[:n]]
