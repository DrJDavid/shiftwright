"""Greedy starting schedule, used only as a CP-SAT hint (never returned as is).

Lazy greedy: repeatedly add the candidate shift with the largest (gap penalty it removes − its
cost). Gains only shrink as demand gets covered, so a popped candidate whose recomputed gain is
still ≥ the next one in the heap is the true best. It respects the rules that make a hint useless
when broken (one shift per day, weekly caps, budget, max days, rest between shifts); the solver
repairs anything else.
"""
from __future__ import annotations

import heapq
from typing import Optional

from shiftwright_contracts.models import ConstraintKind, LawRuleType, Strength

from .prep import Prep, money

ALWAYS_STAFFED_DOLLARS_PER_HOUR = 1000.0  # greedy-only weight: cover hard always_staffed first


def greedy(p: Prep, seed: Optional[tuple[set[int], dict[tuple[str, int], str]]] = None,
           ) -> tuple[set[int], dict[tuple[str, int], str]]:
    """Returns (chosen candidate idxs, {(emp, abs slot): role}). `seed` = shifts already chosen."""
    slot_h = p.slot / 60
    pen = {r.id: money(r.gap_penalty_per_hour * slot_h) for r in p.cfg.roles}
    need = dict(p.demand)
    bonus: dict[tuple[str, int], int] = {}  # one-headcount bonus for always_staffed slots
    for c in p.constraints:
        if c.kind == ConstraintKind.always_staffed:
            rid = c.params.get("role_id")
            w = ALWAYS_STAFFED_DOLLARS_PER_HOUR if c.strength == Strength.hard else c.weight_dollars
            which = c.params.get("windows", "store_hours")
            for d, (lo, hi) in (p.store_open if which == "store_hours" else p.windows).items():
                for t in range(lo - lo % p.slot, hi, p.slot):
                    bonus[(rid, d * 1440 + t)] = money(w * slot_h)
    staffed: dict[tuple[str, int, int], int] = {}  # (role, slot, sub-interval) -> headcount
    subs = p.sub_bounds()
    sub_w = [(u1 - u0) / p.slot for u0, u1 in subs]

    max_days = {e: 7 for e in p.emps}
    for c in p.constraints:
        if c.kind == ConstraintKind.max_days_per_week and c.strength == Strength.hard:
            for eid in p.emps:
                if p.applies(c, eid):
                    max_days[eid] = min(max_days[eid], int(c.params["days"]))
    rest = {e: 0 for e in p.emps}
    for c in p.constraints:
        if c.kind == ConstraintKind.min_rest_between_shifts:
            for eid in p.emps:
                if p.applies(c, eid):
                    rest[eid] = max(rest[eid], int(c.params["minutes"]))
    for lr in p.law_of(LawRuleType.min_rest_between_shifts):
        for eid in rest:
            rest[eid] = max(rest[eid], int(lr.params["minutes"]))
    cap = {e.id: min(c for c, _, _ in p.effective_max_minutes(e)) for e in p.cfg.employees}
    b = p.cfg.budget
    hours_left = int(round((b.weekly_hours_cap + sum(a.extra_hours for a in b.approvals)) * 60))
    dollars_left = (None if b.weekly_dollar_cap is None else
                    money(b.weekly_dollar_cap + sum(a.extra_dollars for a in b.approvals)))

    used_min = {e: 0 for e in p.emps}
    days_on: dict[str, dict[int, tuple[int, int]]] = {e: {} for e in p.emps}  # day -> (abs start, abs end)
    chosen: set[int] = set()
    roles_at: dict[tuple[str, int], str] = {}

    def value(c) -> tuple[int, dict[int, str]]:
        g, pick = 0, {}
        for a in c.work_slots:
            best, br = 0, None
            for r in p.allowed_roles[c.emp]:
                v = (pen.get(r, 0) if need.get((r, a), 0) > 0 else 0)
                if bonus.get((r, a)):
                    brk = c.part.get(a, 0)
                    v += int(bonus[(r, a)] * sum(w for k, w in enumerate(sub_w)
                                                  if not brk >> k & 1 and not staffed.get((r, a, k))))
                if v > best:
                    best, br = v, r
            if br is not None:
                g += best
                pick[a] = br
        return g - c.wage_units - c.pref_units, pick

    def allowed(c) -> bool:
        on = days_on[c.emp]
        if c.day in on or len(on) >= max_days[c.emp]:
            return False
        if used_min[c.emp] + c.paid_min > cap[c.emp] or c.paid_min > hours_left:
            return False
        if dollars_left is not None and c.wage_units > dollars_left:
            return False
        for d, (s0, e0) in on.items():
            if d == c.day - 1 and c.abs_start - e0 < rest[c.emp]:
                return False
            if d == c.day + 1 and s0 - c.abs_end < rest[c.emp]:
                return False
            if s0 < c.abs_end and c.abs_start < e0:
                return False
        return True

    by_idx = {c.idx: c for c in p.cands}

    def take(c, pick) -> None:
        nonlocal hours_left, dollars_left
        chosen.add(c.idx)
        days_on[c.emp][c.day] = (c.abs_start, c.abs_end)
        used_min[c.emp] += c.paid_min
        hours_left -= c.paid_min
        if dollars_left is not None:
            dollars_left -= c.wage_units
        for a in c.work_slots:
            r = pick.get(a) or p.allowed_roles[c.emp][0]
            roles_at[(c.emp, a)] = r
            if need.get((r, a), 0) > 0:
                need[(r, a)] -= 1
            brk = c.part.get(a, 0)
            for k in range(len(subs)):
                if not brk >> k & 1:
                    staffed[(r, a, k)] = staffed.get((r, a, k), 0) + 1

    if seed is not None:
        for idx in seed[0]:
            c = by_idx[idx]
            take(c, {a: seed[1][(c.emp, a)] for a in c.work_slots if (c.emp, a) in seed[1]})

    heap = []
    for c in p.cands:
        g, _ = value(c)
        if g > 0:
            heap.append((-g, c.idx))
    heapq.heapify(heap)
    while heap:
        _, idx = heapq.heappop(heap)
        c = by_idx[idx]
        if not allowed(c):
            continue
        g, pick = value(c)
        if g <= 0:
            continue
        if heap and g < -heap[0][0]:
            heapq.heappush(heap, (-g, idx))
            continue
        take(c, pick)
    return chosen, roles_at


__all__ = ["greedy"]
