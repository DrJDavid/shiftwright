"""Fast, proven infeasibility check for hard `always_staffed` rules.

For each day, the fewest shifts (1, 2, or "3+") that people who may work the role need to keep it
staffed through the window, breaks included, is found exactly with slot bitmasks. If the week's
sum exceeds the days those people can work (availability, max_days_per_week), the hard rules
cannot all hold.
This is a lower-bound argument, so it never reports a feasible config as infeasible.
"""
from __future__ import annotations

from typing import Optional

from shiftwright_contracts.models import AvailabilityKind, ConstraintKind, Infeasibility, Strength

from .model import max_shifts_per_day
from .prep import DAY, Prep, _avail_for_day


def _maximal(masks: set[int]) -> list[int]:
    ms = sorted(masks, key=lambda m: -bin(m).count("1"))
    out: list[int] = []
    for m in ms:
        if not any(m & o == m for o in out):
            out.append(m)
    return out


def _day_min_shifts(cands: list, slots: list[int], subs: list, split: bool = False) -> int:
    """Exact minimum number of shifts (one per person, or with `split` possibly two by the same
    person) whose worked slots cover every slot, capped at 3 (returns 3 for "3 or more"); 0 if no
    slots, -1 if no cover exists at all."""
    if not slots:
        return 0
    nsub = len(subs)
    bit = {a: i * nsub for i, a in enumerate(slots)}  # one bit per (slot, sub-interval)
    full = (1 << (len(slots) * nsub)) - 1
    per_emp: dict[str, set[int]] = {}
    for c in cands:
        m = 0
        for a in c.work_slots:
            if a not in bit:
                continue
            brk = c.part.get(a, 0)
            for k in range(nsub):
                if not brk >> k & 1:
                    m |= 1 << (bit[a] + k)
        if m:
            per_emp.setdefault(c.emp, set()).add(m)
    masks = {e: _maximal(ms) for e, ms in per_emp.items()}
    union = 0
    for ms in masks.values():
        for m in ms:
            union |= m
    if union != full:
        return -1
    if any(m == full for ms in masks.values() for m in ms):
        return 1
    emps = sorted(masks)
    for i, e1 in enumerate(emps):
        for e2 in emps[i if split else i + 1:]:
            for a in masks[e1]:
                need = full & ~a
                if any(b & need == need for b in masks[e2]):
                    return 2
    return 3


def always_staffed_conflict(p: Prep) -> Optional[Infeasibility]:
    for con in p.constraints:
        if con.kind != ConstraintKind.always_staffed or con.strength != Strength.hard:
            continue
        rid = con.params.get("role_id")
        which = con.params.get("windows", "store_hours")
        elig = sorted(e for e, rs in p.allowed_roles.items() if rid in rs)
        if not elig:
            return Infeasibility(conflicting_constraint_ids=[con.id],
                                 summary=f"Rule {con.id} needs {rid} staffed at all times, but nobody may work {rid}.")
        cands = [c for c in p.cands if c.emp in elig]
        if any(c.abs_end > (c.day + 1) * DAY for c in cands):
            continue  # overnight shifts: per-day bound would not be valid
        per_day = max_shifts_per_day(p)
        need_shifts = need_min = 0  # need_shifts: person-days (each gives at most per_day shifts)
        for d, (lo, hi) in sorted((p.store_open if which == "store_hours" else p.windows).items()):
            slots = [d * DAY + t for t in range(lo - lo % p.slot, hi, p.slot)]
            n = _day_min_shifts([c for c in cands if c.day == d], slots, p.sub_bounds(), per_day > 1)
            if n == -1:
                unavail = [f"employee:{e}.availability" for e in elig
                           if any(a.kind == AvailabilityKind.unavailable for a in _avail_for_day(p, p.emps[e], d))]
                return _report(p, con, elig, f"On {DAY_NAMES[d]}, nobody who may work {rid} can keep it staffed "
                                             f"for the whole window (availability, shift length and breaks).",
                               hours=False, extra_other=unavail)
            need_shifts += -(-n // per_day)
            need_min += len(slots) * p.slot
        hour_cap = sum(min(c for c, _, _ in p.effective_max_minutes(p.emps[eid])) for eid in elig)
        if need_min > hour_cap:
            return _report(p, con, elig,
                           f"Keeping {rid} staffed all week needs at least {need_min / 60:g} paid hours from "
                           f"{_people(elig)} who may work it, but their weekly limits allow {hour_cap / 60:g} h.",
                           hours=True)
        max_days_ids = []
        day_cap = 0
        for eid in elig:
            lim = len({c.day for c in cands if c.emp == eid})
            for c in p.constraints:
                if c.kind == ConstraintKind.max_days_per_week and c.strength == Strength.hard and p.applies(c, eid):
                    if int(c.params["days"]) < lim:
                        lim = int(c.params["days"])
                        max_days_ids.append(c.id)
            day_cap += lim
        if need_shifts > day_cap:
            what = (f"{need_shifts} shifts" if per_day == 1 else
                    f"{need_shifts} working days (at most {per_day} shifts per person per day)")
            return _report(p, con, elig,
                           f"Keeping {rid} staffed all week needs at least {what} by people who "
                           f"may work it (breaks must be covered too), but {_people(elig)} can work "
                           f"at most {day_cap} days in total.", hours=False,
                           extra_cons=sorted(set(max_days_ids)))
    return None


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _people(elig: list[str]) -> str:
    return f"the {len(elig)} people" if len(elig) != 1 else f"the only person ({elig[0]})"


def _report(p: Prep, con, elig: list[str], why: str, hours: bool,
            extra_cons: list[str] | None = None, extra_other: list[str] | None = None) -> Infeasibility:
    laws = [] if hours else [r.id for r in p.meal_rules] + ([p.rest_rule.id] if p.rest_rule else [])
    if p.daily_ot is not None and not p.cfg.budget.overtime_allowed and not hours:
        laws.append(p.daily_ot.id)
    other = list(extra_other or [])
    if hours:
        for eid in elig:
            for _, bucket, ident in p.effective_max_minutes(p.emps[eid]):
                (other if bucket == "employee" else laws).append(ident)
    cons = [con.id] + (extra_cons or [])
    for c in ([] if hours else p.constraints):
        if c.strength == Strength.hard and c.kind in (ConstraintKind.min_shift_length, ConstraintKind.max_shift_length):
            cons.append(c.id)
    return Infeasibility(conflicting_constraint_ids=sorted(set(cons)), conflicting_law_rule_ids=sorted(set(laws)),
                         conflicting_other=sorted(set(other)), summary=why)
