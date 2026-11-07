"""Greedy starting schedule, used only as a CP-SAT hint (never returned as is).

Lazy greedy: repeatedly add the candidate shift with the largest tier-weighted coverage gain
(SEMANTICS #25), cost breaking ties. Gains only shrink as demand gets covered, so a popped
candidate whose recomputed gain is still ≥ the next one in the heap is the true best. It respects the rules that make a hint useless
when broken (one shift per day, weekly caps, budget, max days, rest between shifts); the solver
repairs anything else.
"""
from __future__ import annotations

import heapq
import os
from typing import Optional

from shiftwright_contracts.models import ConstraintKind, LawRuleType, Strength

from .lex import tier_weights
from .prep import Prep, money

HARD = "hard"
MIN_UTILIZATION = float(os.environ.get("ENGINE_GREEDY_MIN_UTIL", "0.7"))


def greedy(p: Prep, seed: Optional[tuple[set[int], dict[tuple[str, int], str]]] = None,
           ) -> tuple[set[int], dict[tuple[str, int], str]]:
    """Returns (chosen candidate idxs, {(emp, abs slot): role}). `seed` = shifts already chosen."""
    w_role, w_always, _ = tier_weights(p, with_always=True)
    pen = {r: w * p.slot for r, w in w_role.items()}  # coverage weight of one demanded slot
    need = dict(p.demand)
    # always_staffed slots: hard ones are the top coverage tier; soft ones a cost credit ($ units/min)
    always: dict[tuple[str, int], object] = {}
    for c in p.constraints:
        if c.kind == ConstraintKind.always_staffed:
            rid = c.params.get("role_id")
            kind = HARD if c.strength == Strength.hard else money(c.weight_dollars / 60)
            which = c.params.get("windows", "store_hours")
            for d, (lo, hi) in (p.store_open if which == "store_hours" else p.windows).items():
                for t in range(lo - lo % p.slot, hi, p.slot):
                    if always.get((rid, d * 1440 + t)) != HARD:
                        always[(rid, d * 1440 + t)] = kind
    staffed: dict[tuple[str, int, int], int] = {}  # (role, slot, sub-interval) -> headcount
    subs = p.sub_bounds()
    hard_roles = {r for (r, _a), k in always.items() if k == HARD}
    exempt = {e for e, rs in p.allowed_roles.items() if hard_roles & set(rs)}  # keep hard always_staffed coverable

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

    def value(c) -> tuple[int, int, dict[int, str]]:
        """(coverage gain, cost net of soft always_staffed credit, roles). Gain 0 when fewer than
        MIN_UTILIZATION of the shift's paid minutes would cover demand: the hint leaves those hours
        in the budget for the solver to place."""
        cov, credit, pick, used = 0, 0, {}, 0
        for a in c.work_slots:
            best, br = (0, 0), None
            for r in p.allowed_roles[c.emp]:
                v = (pen.get(r, 0) if need.get((r, a), 0) > 0 else 0)
                cr = 0
                kind = always.get((r, a))
                if kind is not None:
                    brk = c.part.get(a, 0)
                    mins = sum(u1 - u0 for k, (u0, u1) in enumerate(subs)
                               if not brk >> k & 1 and not staffed.get((r, a, k)))
                    if kind == HARD:
                        v += w_always * mins
                    else:
                        cr = kind * mins
                if (v, cr) > best:
                    best, br = (v, cr), r
            if br is not None:
                cov += best[0]
                credit += best[1]
                pick[a] = br
                used += best[0] > 0
        if c.emp not in exempt and used * p.slot < MIN_UTILIZATION * c.paid_min:
            cov = 0
        return cov, c.wage_units + c.pref_units - credit, pick

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

    def key(c, cov, cost) -> tuple[int, int]:
        return -cov, cost

    heap = []
    for c in p.cands:
        cov, cost, _ = value(c)
        if cov > 0 or cost < 0:
            heap.append((*key(c, cov, cost), c.idx))
    heapq.heapify(heap)
    while heap:
        _, _, idx = heapq.heappop(heap)
        c = by_idx[idx]
        if not allowed(c):
            continue
        cov, cost, pick = value(c)
        if cov <= 0 and cost >= 0:
            continue
        k = key(c, cov, cost)
        if heap and k > heap[0][:2]:
            heapq.heappush(heap, (*k, idx))
            continue
        take(c, pick)
    return chosen, roles_at



def repair(p: Prep, chosen: set[int], roles_at: dict[tuple[str, int], str], max_passes: int = 3,
           ) -> tuple[set[int], dict[tuple[str, int], str], int]:
    """Coverage-first finishing (SEMANTICS #25): fill demand the solver left open with a legal
    candidate shift, best tier-weighted net gain first: a candidate replacing the shift it overlaps
    (an extension, possibly with its breaks moved; demand the employee stops covering counts
    against it, and hard always_staffed slots are never given up), or a new shift (a day off, or
    a split day under `max_shifts_per_day`). Checks weekly caps, max days, hard rest and
    consecutive days, same-day spacing and law rest, minor daily caps, daily overtime when it isn't
    allowed, hard not_together, the hours and dollar budgets; candidates already carry
    availability, minor, break and shift-length rules.
    The caller re-checks every hard rule with the phase-2 model and drops the repair if it fails.
    Returns (chosen, roles, moves made)."""
    w_role, _, _ = tier_weights(p, with_always=False)
    if not w_role:
        return chosen, roles_at, 0
    chosen, roles_at = set(chosen), dict(roles_at)
    have: dict[tuple[str, int], int] = {}
    for (_e, a), r in roles_at.items():
        have[(r, a)] = have.get((r, a), 0) + 1
    n_max = max(1, int(getattr(p.cfg.store, "max_shifts_per_day", 1) or 1))
    by_ed: dict[tuple[str, int], list] = {}
    used = {e: 0 for e in p.emps}
    for i in chosen:
        c = p.cands[i]
        by_ed.setdefault((c.emp, c.day), []).append(c)
        used[c.emp] = used.get(c.emp, 0) + c.paid_min
    b = p.cfg.budget
    hours_left = int(round((b.weekly_hours_cap + sum(a.extra_hours for a in b.approvals)) * 60)) - sum(used.values())
    dollars_left = (None if b.weekly_dollar_cap is None else
                    money(b.weekly_dollar_cap + sum(a.extra_dollars for a in b.approvals))
                    - sum(p.cands[i].wage_units for i in chosen))
    cap = {e.id: min(c for c, _, _ in p.effective_max_minutes(e)) for e in p.cfg.employees}
    max_days = {e: 7 for e in p.emps}
    max_consec = {e: 7 for e in p.emps}
    rest = {e: 0 for e in p.emps}
    apart: list[tuple[str, str]] = []
    only_role: dict[str, str] = {}
    for con in p.constraints:
        if con.strength != Strength.hard:
            continue
        for eid in p.emps:
            if not p.applies(con, eid):
                continue
            if con.kind == ConstraintKind.max_days_per_week:
                max_days[eid] = min(max_days[eid], int(con.params["days"]))
            elif con.kind == ConstraintKind.max_consecutive_days:
                max_consec[eid] = min(max_consec[eid], int(con.params["days"]))
            elif con.kind == ConstraintKind.min_rest_between_shifts:
                rest[eid] = max(rest[eid], int(con.params["minutes"]))
        if con.kind == ConstraintKind.not_together and len(con.params.get("employee_ids", [])) == 2:
            apart.append(tuple(con.params["employee_ids"]))
        if con.kind == ConstraintKind.preferred_role and con.params.get("employee_id") in p.emps:
            only_role[con.params["employee_id"]] = con.params.get("role_id")
        if con.kind == ConstraintKind.fair_spread:
            return chosen, roles_at, 0  # hard fair_spread: leave it to the solver
    for lr in p.law_of(LawRuleType.min_rest_between_shifts):
        for eid in rest:
            rest[eid] = max(rest[eid], int(lr.params["minutes"]))

    emp_roles: dict[str, list[str]] = {}
    for eid in p.emps:
        rs = p.allowed_roles.get(eid, [])
        emp_roles[eid] = [only_role[eid]] if eid in only_role and only_role[eid] in rs else list(rs)

    def roles_for(eid: str) -> list[str]:
        return emp_roles[eid]

    always_roles = {c.params.get("role_id") for c in p.constraints
                    if c.kind == ConstraintKind.always_staffed and c.strength == Strength.hard}
    same_day_rest = max([int(lr.params["minutes"]) for lr in p.law_of(LawRuleType.min_rest_between_shifts)
                         if not lr.params.get("excludes_same_day_split")], default=0)
    ot_cap = (int(p.daily_ot.params["threshold_hours"] * 60)
              if p.daily_ot is not None and not b.overtime_allowed else None)

    def gain(c, old, open_e: set[int]) -> tuple[int, dict[int, str]] | None:
        """Net tier-weighted minutes gained by working `c` instead of `old`: open demand on newly
        worked slots minus demand the employee stops covering (a slot now partly on break counts as
        lost). None if a hard always_staffed slot would be given up. `open_e`: slots with open
        demand for one of the employee's roles."""
        g, pick = 0, {}
        old_slots = set(old.work_slots) if old is not None else set()
        new_slots = open_e.intersection(c.work_slots)
        if not new_slots - old_slots:
            return None
        new_slots = set(c.work_slots)

        def lose(a) -> int:
            r = roles_at.get((c.emp, a))
            if r in always_roles:
                return -1
            return w_role.get(r, 0) * p.slot if have.get((r, a), 0) <= p.demand.get((r, a), 0) else 0
        for a in old_slots:
            if a not in new_slots or c.part.get(a, 0) & ~old.part.get(a, 0):
                v = lose(a)
                if v < 0:
                    return None
                g -= v
        for a in new_slots - old_slots:
            if a not in open_e or c.part.get(a, 0):
                continue
            best, br = 0, None
            for r in roles_for(c.emp):
                if have.get((r, a), 0) < p.demand.get((r, a), 0) and w_role.get(r, 0) > best:
                    best, br = w_role[r], r
            if br is not None:
                g += best * p.slot
                pick[a] = br
        return g, pick

    def legal(c, old) -> bool:
        add = c.paid_min - (old.paid_min if old is not None else 0)
        if add > hours_left or used[c.emp] + add > cap[c.emp]:
            return False
        if dollars_left is not None and c.wage_units - (old.wage_units if old is not None else 0) > dollars_left:
            return False
        others = [o for o in by_ed.get((c.emp, c.day), []) if o is not old]
        for o in others:  # split day: no overlap, a slot apart, and same-day law rest
            if c.abs_start < o.abs_end + max(p.slot, same_day_rest) and o.abs_start < c.abs_end + max(p.slot, same_day_rest):
                return False
        day_paid = c.paid_min + sum(o.paid_min for o in others)
        minor_cap = p.minor_day_cap(p.emps[c.emp], c.day)
        if (minor_cap is not None and day_paid > minor_cap) or (ot_cap is not None and day_paid > ot_cap):
            return False
        days = {d for (e, d) in by_ed if e == c.emp} | {c.day}
        if len(days) > max_days[c.emp]:
            return False
        run = 0
        for d in range(7):
            run = run + 1 if d in days else 0
            if run > max_consec[c.emp]:
                return False
        for d in (c.day - 1, c.day + 1):
            for o in by_ed.get((c.emp, d), []):
                if d < c.day and c.abs_start - o.abs_end < rest[c.emp]:
                    return False
                if d > c.day and o.abs_start - c.abs_end < rest[c.emp]:
                    return False
        for ea, eb in apart:
            other = eb if c.emp == ea else ea if c.emp == eb else None
            if other is None:
                continue
            for d in (c.day - 1, c.day, c.day + 1):
                for o in by_ed.get((other, d), []):
                    if o.abs_start < c.abs_end and c.abs_start < o.abs_end:
                        return False
        return True

    def replaced(c):
        """The shift of that employee-day `c` would replace, None for a new shift; False if neither."""
        mine = by_ed.get((c.emp, c.day), [])
        hit = [o for o in mine if o.abs_start < c.abs_end and c.abs_start < o.abs_end]
        if len(hit) > 1 or (not hit and len(mine) >= n_max):
            return False
        return hit[0] if hit else None

    moves = 0
    for _ in range(max_passes):
        open_by_role: dict[str, set[int]] = {}
        for (r, a), dem in p.demand.items():
            if r in w_role and have.get((r, a), 0) < dem:
                open_by_role.setdefault(r, set()).add(a)
        open_for = {eid: set().union(*(open_by_role.get(r, set()) for r in rs)) if rs else set()
                    for eid, rs in emp_roles.items()}
        opts = []
        for c in p.cands:
            if open_for[c.emp].isdisjoint(c.work_slots):
                continue
            old = replaced(c)
            if old is False:
                continue
            res = gain(c, old, open_for[c.emp])
            if res is not None and res[0] > 0:
                opts.append((-res[0], c.wage_units - (old.wage_units if old is not None else 0), c.idx))
        opts.sort()
        changed = False
        for _g, _cost, idx in opts:
            c = p.cands[idx]
            old = replaced(c)
            if old is False:
                continue
            res = gain(c, old, open_for[c.emp])
            if res is None or res[0] <= 0 or not legal(c, old):
                continue
            pick = res[1]
            add = c.paid_min - (old.paid_min if old is not None else 0)
            hours_left -= add
            used[c.emp] += add
            if dollars_left is not None:
                dollars_left -= c.wage_units - (old.wage_units if old is not None else 0)
            if old is not None:
                chosen.discard(old.idx)
                for a in old.work_slots:
                    if a not in c.work_slots:
                        r = roles_at.pop((c.emp, a), None)
                        if r is not None:
                            have[(r, a)] -= 1
            chosen.add(c.idx)
            by_ed[(c.emp, c.day)] = [o for o in by_ed.get((c.emp, c.day), []) if o is not old] + [c]
            for a in c.work_slots:
                if a in pick:
                    roles_at[(c.emp, a)] = pick[a]
                    have[(pick[a], a)] = have.get((pick[a], a), 0) + 1
                elif (c.emp, a) not in roles_at:
                    roles_at[(c.emp, a)] = roles_for(c.emp)[0]
                    have[(roles_at[(c.emp, a)], a)] = have.get((roles_at[(c.emp, a)], a), 0) + 1
            moves += 1
            changed = True
        if not changed:
            break
    return chosen, roles_at, moves


__all__ = ["greedy", "repair"]
