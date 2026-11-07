"""Preprocessing: turn a StoreConfig into slot grids, rule lookups and candidate shifts.

Time inside the engine is ABSOLUTE week minutes: abs = day * 1440 + minute_of_day.
This lets overnight shifts cover the next day's slots without special cases.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from shiftwright_contracts.models import (
    AvailabilityKind,
    Break,
    Constraint,
    ConstraintKind,
    Employee,
    LawRule,
    LawRuleType,
    RuleStatus,
    StoreConfig,
    Strength,
)

DAY = 1440
SCALE = 10_000  # objective units per dollar (0.01 cent resolution)

# Engine defaults used ONLY when the config has no shift-length constraint. These are
# product defaults (not law) and are reported in solver_stats.
DEFAULT_MIN_SHIFT = 180
DEFAULT_MAX_SHIFT = 600

# v1.1: breaks keep their exact length (rounded up to 5 min) and start on the slot grid, so a 10-min
# rest break covers the first 10 min of a slot. Coverage is then exact per minute. Env
# ENGINE_EXACT_BREAKS=0 falls back to breaks rounded up to whole slots.
BREAK_GRANULARITY = 5
EXACT_BREAKS = os.environ.get("ENGINE_EXACT_BREAKS", "1") != "0"


def money(dollars: float) -> int:
    return int(round(dollars * SCALE))


@dataclass
class Cand:
    idx: int
    emp: str
    day: int
    start: int  # day-local
    end: int  # day-local
    breaks: list[Break]
    on_slots: list[int]  # abs slot starts inside [start, end)
    work_slots: list[int]  # on_slots where some minute is worked (not wholly on break)
    paid_min: int
    wage_units: int  # wage + daily OT premium, objective units
    daily_ot_min: int
    pref_units: int  # availability preference penalty (may be negative for preferred_on)
    pref_detail: list[tuple[str, float, float]] = field(default_factory=list)  # (kind, hours, dollars)
    is_open: bool = False
    is_close: bool = False
    weekend: bool = False
    extra_units: int = 0  # objective-only cost (fixer: call-in disruption + premiums)
    part: dict[int, int] = field(default_factory=dict)  # work slot -> bitmask of sub-intervals on break
    untipped_extra_units: int = 0  # wage_units assume the tipped rate; add this if any slot is untipped

    @property
    def abs_start(self) -> int:
        return self.day * DAY + self.start

    @property
    def abs_end(self) -> int:
        return self.day * DAY + self.end


@dataclass
class Prep:
    cfg: StoreConfig
    slot: int
    emps: dict[str, Employee]
    constraints: list[Constraint]  # confirmed only
    laws: list[LawRule]
    windows: dict[int, tuple[int, int]]  # day -> staff window (local)
    store_open: dict[int, tuple[int, int]]  # day -> (open, close) local
    allowed_roles: dict[str, list[str]]
    blocked_roles: dict[str, dict[str, tuple[str, Optional[str]]]]  # emp -> role -> (code, law id)
    demand: dict[tuple[str, int], int]  # (role, abs slot) -> headcount
    cands: list[Cand]
    by_emp_day: dict[tuple[str, int], list[Cand]]
    weekly_ot: Optional[LawRule]
    daily_ot: Optional[LawRule]
    meal_rules: list[LawRule]
    rest_rule: Optional[LawRule]
    notes: list[str]
    sub: list[int] = field(default_factory=lambda: [0])  # sub-interval boundaries within a slot (+ slot)
    bv_cache: dict = field(default_factory=dict)
    tipped_roles: set = field(default_factory=set)

    def sub_bounds(self) -> list[tuple[int, int]]:
        b = self.sub + [self.slot]
        return [(b[i], b[i + 1]) for i in range(len(b) - 1)]

    def tipped_capable(self, e: Employee) -> bool:
        """SEMANTICS #20: tipped rate possible (tipped wage set, may work a tipped role)."""
        return e.tipped_wage_per_hour is not None and any(r in self.tipped_roles for r in self.allowed_roles.get(e.id, []))

    def base_rate(self, e: Employee) -> float:
        return e.tipped_wage_per_hour if self.tipped_capable(e) else e.wage_per_hour

    def shift_rate(self, e: Employee, role_ids) -> float:
        """Rate for a whole shift: tipped only if every segment is a tipped role (#20)."""
        rs = list(role_ids)
        if e.tipped_wage_per_hour is not None and rs and all(r in self.tipped_roles for r in rs):
            return e.tipped_wage_per_hour
        return e.wage_per_hour

    def law_of(self, t: LawRuleType) -> list[LawRule]:
        return [r for r in self.laws if r.type == t]

    def applies(self, c: Constraint, eid: str) -> bool:
        return c.applies_to_employee_ids is None or eid in c.applies_to_employee_ids

    def minor_rules(self, e: Employee) -> list[LawRule]:
        """Matching minor_limits rules, filtered by Store.school_week (SEMANTICS #8): None = all,
        True = school-week rules only, False = non-school rules only. A rule without a
        `school_week` key applies either way."""
        sw = self.cfg.store.school_week
        return [r for r in self.law_of(LawRuleType.minor_limits)
                if r.params.get("age_min", 0) <= e.age <= r.params.get("age_max", -1)
                and (sw is None or r.params.get("school_week") is None or bool(r.params["school_week"]) == sw)]

    def minor_latest_end(self, e: Employee, day: int) -> Optional[int]:
        """Latest shift end for a minor on `day` (same reading as the validator): a rule's
        `latest_end_before_non_school_day` applies on Fri/Sat nights for school-week rules and on
        every day for non-school rules; otherwise `latest_end`. Most restrictive rule wins."""
        ends = []
        for r in self.minor_rules(e):
            pr = r.params
            late = pr.get("latest_end_before_non_school_day")
            if late is not None and (not pr.get("school_week") or day in (4, 5)):
                ends.append(int(late))
            elif pr.get("latest_end") is not None:
                ends.append(int(pr["latest_end"]))
        return min(ends) if ends else None

    def minor_day_cap(self, e: Employee, day: int) -> Optional[int]:
        """Paid-minute cap for a minor on `day`. School-week rules use max_hours_day on Mon-Fri and
        max_hours_non_school_day (if given) on Sat/Sun; all applicable rules apply (most restrictive)."""
        caps = []
        for r in self.minor_rules(e):
            pr = r.params
            v = pr.get("max_hours_day")
            if pr.get("school_week") and day >= 5 and pr.get("max_hours_non_school_day") is not None:
                v = pr["max_hours_non_school_day"]
            if v is not None:
                caps.append(int(round(v * 60)))
        return min(caps) if caps else None

    def shift_bounds(self, eid: str) -> tuple[int, int]:
        lo, hi = None, None
        for c in self.constraints:
            if c.strength != Strength.hard or not self.applies(c, eid):
                continue
            if c.kind == ConstraintKind.min_shift_length:
                lo = max(lo or 0, int(c.params["minutes"]))
            elif c.kind == ConstraintKind.max_shift_length:
                v = int(c.params["minutes"])
                hi = v if hi is None else min(hi, v)
        lo = DEFAULT_MIN_SHIFT if lo is None else lo
        hi = DEFAULT_MAX_SHIFT if hi is None else hi
        s = self.slot
        lo = max(s, -(-lo // s) * s)
        hi = (hi // s) * s
        return lo, hi

    def effective_max_minutes(self, e: Employee) -> list[tuple[int, str, Optional[str]]]:
        """(minutes cap, kind, id) caps on weekly paid minutes for this employee."""
        caps = [(int(round(e.max_hours_week * 60)), "employee", f"employee:{e.id}.max_hours_week")]
        for r in self.minor_rules(e):
            if r.params.get("max_hours_week") is not None:
                caps.append((int(round(r.params["max_hours_week"] * 60)), "law", r.id))
        if self.weekly_ot and not self.cfg.budget.overtime_allowed:
            caps.append((int(round(self.weekly_ot.params["threshold_hours"] * 60)), "law", self.weekly_ot.id))
        return caps


def _round_up(v: int, s: int) -> int:
    return -(-v // s) * s


def _round_down(v: int, s: int) -> int:
    return (v // s) * s


MEAL_SHIFTS = (0, -60, -120)  # meal-position variants (minutes earlier than the default position)


REST_MODES = ("even", "early", "late")


def break_variants(p: Prep, start: int, length: int, flexible: bool = False) -> list[list[Break]]:
    """Break layouts for a shift: the default plus meals moved earlier, so overlapping shifts
    can cover each other's meals. With `flexible` (employees in a hard always_staffed role), rest
    breaks are also tried packed early or late, so two leaders can cover each other's breaks.
    Deduplicated; empty list if nothing fits."""
    key = (length, flexible)
    rel = p.bv_cache.get(key)
    if rel is None:  # layouts are relative to the start (starts are on the slot grid)
        rel, seen = [], set()
        needs_meal = any(length > int(m.params["after_minutes"]) for m in p.meal_rules)
        for mode in (REST_MODES if flexible and p.rest_rule is not None else ("even",)):
            for sh in (MEAL_SHIFTS if needs_meal else (0,)):
                b = place_breaks(p, 0, length, sh, mode)
                if b is None:
                    continue
                k = tuple((x.start, x.end, x.kind, x.paid) for x in b)
                if k not in seen:
                    seen.add(k)
                    rel.append(k)
        p.bv_cache[key] = rel
    return [[Break.model_construct(start=start + a, end=start + b, kind=kd, paid=pd) for a, b, kd, pd in lay]
            for lay in rel]


def break_minutes(p: Prep, duration: int) -> int:
    return _round_up(duration, BREAK_GRANULARITY) if EXACT_BREAKS else _round_up(duration, p.slot)


def place_breaks(p: Prep, start: int, length: int, meal_shift: int = 0,
                 rest_mode: str = "even") -> Optional[list[Break]]:
    """Deterministic breaks for a shift [start, start+length). None if they cannot fit."""
    s = p.slot
    end = start + length
    taken: list[tuple[int, int]] = []
    out: list[Break] = []

    def free(a: int, b: int) -> bool:
        return a >= start + s and b <= end - s and all(b <= x or a >= y for x, y in taken)

    # Meals: one per meal rule (tier) whose threshold the shift exceeds. Placed so the break
    # ENDS by `latest_start_minute_of_shift` (protective under either reading of "latest start"),
    # or at the midpoint if no latest start is given.
    for m in sorted(p.meal_rules, key=lambda r: r.params["after_minutes"]):
        if length <= int(m.params["after_minutes"]):
            continue
        dur = break_minutes(p, int(m.params["duration"]))
        latest = m.params.get("latest_start_minute_of_shift")
        if latest is not None:
            bs = start + min(_round_down(int(latest) - dur, s), _round_down(length - s - dur, s))
        else:
            bs = start + _round_down((length - dur) // 2, s)
        bs += _round_down(meal_shift, s) if meal_shift >= 0 else -_round_up(-meal_shift, s)
        while bs >= start + s and not free(bs, bs + dur):
            bs -= s
        if not free(bs, bs + dur):
            return None
        taken.append((bs, bs + dur))
        out.append(Break(start=bs, end=bs + dur, kind="meal", paid=bool(m.params.get("paid", False))))

    r = p.rest_rule
    if r is not None:
        per = int(r.params["per_minutes_worked"])
        # floor(span / per), and at least 1 at or above `not_required_under_minutes` (WS2 semantics #6).
        n = length // per if per > 0 else 0
        nru = r.params.get("not_required_under_minutes")
        if nru is not None and length >= int(nru):
            n = max(n, 1)
        dur = break_minutes(p, int(r.params["duration"]))
        for k in range(1, n + 1):
            target = start + _round_down(k * length // (n + 1), s)
            if rest_mode == "early":
                target = start + s
            elif rest_mode == "late":
                target = start + _round_down(length - s - dur, s)
            placed = False
            for off in range(0, length, s):
                for bs in (target + off, target - off):
                    if free(bs, bs + dur):
                        taken.append((bs, bs + dur))
                        out.append(Break(start=bs, end=bs + dur, kind="rest",
                                         paid=bool(r.params.get("paid", True))))
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                return None
    out.sort(key=lambda b: b.start)
    return out


def _avail_for_day(p: Prep, e: Employee, day: int):
    the_date = p.cfg.store.week_start + timedelta(days=day)
    for a in e.availability:
        if a.weekday == day or (a.on_date is not None and a.on_date == the_date):
            yield a


def _pick(laws: list[LawRule], key) -> Optional[LawRule]:
    return min(laws, key=key) if laws else None


def build_prep(cfg: StoreConfig, with_cands: bool = True, start_step: int | None = None,
               length_step: int | None = None, prune: bool = True) -> Prep:
    slot = cfg.store.slot_minutes
    laws = [r for r in (cfg.law_pack.rules if cfg.law_pack else []) if sector_applies(r, cfg.store.sector)]
    constraints = [c for c in cfg.constraints if c.status == RuleStatus.confirmed]
    notes: list[str] = []
    if cfg.law_pack is None:
        notes.append("No law pack supplied; no labor-law rules applied.")

    windows, store_open = {}, {}
    for h in cfg.store.hours:
        if h.close <= h.open:
            continue
        store_open[h.day] = (h.open, h.close)
        windows[h.day] = (h.open - cfg.store.pre_open_minutes, h.close + cfg.store.post_close_minutes)

    p = Prep(
        cfg=cfg, slot=slot, emps={e.id: e for e in cfg.employees}, constraints=constraints, laws=laws,
        windows=windows, store_open=store_open, allowed_roles={}, blocked_roles={}, demand={},
        cands=[], by_emp_day={},
        weekly_ot=_pick([r for r in laws if r.type == LawRuleType.weekly_overtime],
                        lambda r: r.params["threshold_hours"]),
        daily_ot=_pick([r for r in laws if r.type == LawRuleType.daily_overtime],
                       lambda r: r.params["threshold_hours"]),
        meal_rules=[r for r in laws if r.type == LawRuleType.meal_break],
        rest_rule=_pick([r for r in laws if r.type == LawRuleType.rest_break],
                        lambda r: r.params["per_minutes_worked"]),
        notes=notes,
    )

    durs = [int(r.params["duration"]) for r in p.meal_rules] + ([int(p.rest_rule.params["duration"])] if p.rest_rule else [])
    p.sub = sorted({0} | {break_minutes(p, d) % slot for d in durs})

    p.tipped_roles = {r.id for r in cfg.roles if getattr(r, "tipped", False)}

    # Roles each employee may work (training is the hard gate; then age/law).
    roles = {r.id: r for r in cfg.roles}
    prohibited = p.law_of(LawRuleType.minor_prohibited_roles)
    for e in cfg.employees:
        ok, blocked = [], {}
        for rid in e.trained_role_ids:
            if rid not in roles:
                continue
            why = None
            for lr in prohibited:
                lo_age = lr.params.get("age_min")
                if ((lo_age is None or e.age >= lo_age) and e.age < lr.params["age_below"]
                        and set(cfg.role_tags.get(rid, [])) & set(lr.params["role_tags"])):
                    why = ("minor_rule", lr.id)
                    break
            if why is None and e.age < roles[rid].min_age:
                why = ("minor_rule", None)
            if why:
                blocked[rid] = why
            else:
                ok.append(rid)
        p.allowed_roles[e.id] = ok
        p.blocked_roles[e.id] = blocked

    # Demand per (role, abs slot)
    for d in cfg.demand:
        if d.headcount <= 0:
            continue
        t = _round_down(d.start, slot)
        while t < d.end:
            k = (d.role_id, d.day * DAY + t)
            p.demand[k] = p.demand.get(k, 0) + d.headcount
            t += slot

    # Slots where an employee's work can matter: demand or always_staffed for a role they may work,
    # or a preferred_on window. With `prune`, a candidate longer than the minimum whose first or last
    # worked slot is not useful is dropped (the trimmed shift is never worse), and so is one with no
    # useful slot. Employees under a hard min_hours_week or in a hard always_staffed role keep every
    # candidate (break layouts differ, so trimming is not a dominance there).
    useful_by_role: dict[str, set[int]] = {}
    for (rid, a) in p.demand:
        useful_by_role.setdefault(rid, set()).add(a)
    for c in constraints:
        if c.kind == ConstraintKind.always_staffed:
            rid = c.params.get("role_id")
            which = c.params.get("windows", "store_hours")
            for d, (lo_, hi_) in (store_open if which == "store_hours" else windows).items():
                useful_by_role.setdefault(rid, set()).update(
                    d * DAY + t for t in range(_round_down(lo_, slot), hi_, slot))
    always_roles = {c.params.get("role_id") for c in constraints
                    if c.kind == ConstraintKind.always_staffed and c.strength == Strength.hard}
    hard_min_hours = [c for c in constraints
                      if c.kind == ConstraintKind.min_hours_week and c.strength == Strength.hard]

    # Candidate shifts
    for e in (cfg.employees if with_cands else []):
        if not p.allowed_roles[e.id]:
            continue
        flexible = bool(always_roles & set(p.allowed_roles[e.id]))
        useful: Optional[set[int]] = None
        if prune and not flexible and not any(p.applies(c, e.id) and e.min_hours_week > 0 for c in hard_min_hours):
            useful = set().union(*(useful_by_role.get(r, set()) for r in p.allowed_roles[e.id]))
            for a in e.availability:
                if a.kind == AvailabilityKind.preferred_on:
                    days_ = [a.weekday] if a.weekday is not None else [
                        d for d in windows if cfg.store.week_start + timedelta(days=d) == a.on_date]
                    for d in days_:
                        useful.update(d * DAY + t for t in range(_round_down(a.start, slot), a.end, slot))
        lo, hi = p.shift_bounds(e.id)
        minors = p.minor_rules(e)
        earliest = max([r.params["earliest_start"] for r in minors if r.params.get("earliest_start") is not None],
                       default=None)
        week_cap = min(c for c, _, _ in p.effective_max_minutes(e))
        for day, (w0, w1) in sorted(windows.items()):
            avail = list(_avail_for_day(p, e, day))
            unavail = [(a.start, a.end) for a in avail if a.kind == AvailabilityKind.unavailable]
            max_day_min = p.minor_day_cap(e, day)
            latest_end = p.minor_latest_end(e, day)
            lst = p.by_emp_day.setdefault((e.id, day), [])
            for start in range(_round_up(w0, slot), w1, start_step or slot):
                if earliest is not None and start < earliest:
                    continue
                for length in range(lo, hi + 1, length_step or slot):
                    end = start + length
                    if end > w1:
                        break
                    if latest_end is not None and end > latest_end:
                        break
                    if any(a < end and start < b for a, b in unavail):
                        continue
                    for brks in break_variants(p, start, length, flexible):
                        cand = make_cand(p, e, day, start, end, brks, avail, week_cap, max_day_min)
                        if cand is None:
                            continue
                        if useful is not None:
                            work = cand.work_slots
                            if not work or not useful.intersection(work):
                                continue
                            if length > lo and (work[0] not in useful or work[-1] not in useful):
                                continue
                        p.cands.append(cand)
                        lst.append(cand)
    return p


def make_cand(p: Prep, e: Employee, day: int, start: int, end: int, brks: list[Break], avail: list,
              week_cap: int, max_day_min: Optional[int], idx: Optional[int] = None,
              charge_preferences: bool = True, strict: bool = True) -> Optional[Cand]:
    """One candidate shift with its cost terms; None if it breaks a per-shift hard cap
    (weekly cap, minor day cap, daily OT when overtime is not allowed)."""
    cfg, slot = p.cfg, p.slot
    length = end - start
    unpaid = sum(b.end - b.start for b in brks if not b.paid)
    paid = length - unpaid
    if strict and (paid > week_cap or (max_day_min is not None and paid > max_day_min)):
        return None
    daily_ot = 0
    if p.daily_ot is not None:
        thr = int(p.daily_ot.params["threshold_hours"] * 60)
        if paid > thr:
            if strict and not cfg.budget.overtime_allowed:
                return None
            daily_ot = paid - thr
    rate = p.base_rate(e)
    wage = paid / 60 * rate
    if daily_ot:
        wage += daily_ot / 60 * e.wage_per_hour * (p.daily_ot.params["multiplier"] - 1)  # OT on the full wage (#20)
        dbl = p.daily_ot.params.get("double_threshold_hours")
        if dbl is not None and paid > dbl * 60:
            wage += (paid - dbl * 60) / 60 * e.wage_per_hour * (2 - p.daily_ot.params["multiplier"])
    pref, detail = 0.0, []
    for a in (avail if charge_preferences else []):
        if a.kind == AvailabilityKind.unavailable:
            continue
        ov = max(0, min(end, a.end) - max(start, a.start)) / 60
        if a.kind == AvailabilityKind.preferred_off and ov > 0:
            pref += a.weight_dollars * ov
            detail.append(("preferred_off", ov, a.weight_dollars * ov))
        elif a.kind == AvailabilityKind.preferred_on:
            pref -= a.weight_dollars * ov  # constant added in model
    on = [day * DAY + t for t in range(start, end, slot)]
    subs = p.sub_bounds()
    fullmask = (1 << len(subs)) - 1
    masks: dict[int, int] = {}
    for b in brks:
        t = b.start - (b.start - start) % slot
        while t < b.end:
            mk = masks.get(t, 0)
            for k, (u0, u1) in enumerate(subs):
                if b.start < t + u1 and t + u0 < b.end:
                    mk |= 1 << k  # any break minute in a sub-interval takes all of it (conservative)
            masks[t] = mk
            t += slot
    base = day * DAY
    work = [base + t for t in range(start, end, slot) if masks.get(t, 0) != fullmask]
    part = {base + t: mk for t, mk in masks.items() if mk and mk != fullmask}
    o, c = p.store_open.get(day, (start, end))
    return Cand(
        idx=len(p.cands) if idx is None else idx, emp=e.id, day=day, start=start, end=end, breaks=brks,
        on_slots=on, work_slots=work, paid_min=paid, wage_units=money(wage),
        daily_ot_min=daily_ot, pref_units=money(pref), pref_detail=detail,
        is_open=start < o, is_close=end > c, weekend=day in (5, 6), part=part,
        untipped_extra_units=money(paid / 60 * (e.wage_per_hour - rate)) if rate != e.wage_per_hour else 0,
    )


def sector_applies(rule: LawRule, sector) -> bool:
    """SEMANTICS #19: `applies_to` "both" or the store's sector; sector None/other => applies."""
    at = rule.params.get("applies_to")
    if at is None:
        return True
    sec = getattr(sector, "value", sector)
    vals = at if isinstance(at, list) else [at]
    if "both" in vals:
        return True
    if sec is None or sec == "other":
        return True
    return sec in vals
