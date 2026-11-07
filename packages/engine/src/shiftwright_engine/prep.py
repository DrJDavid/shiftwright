"""Preprocessing: turn a StoreConfig into slot grids, rule lookups and candidate shifts.

Time inside the engine is ABSOLUTE week minutes: abs = day * 1440 + minute_of_day.
This lets overnight shifts cover the next day's slots without special cases.
"""
from __future__ import annotations

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
    work_slots: list[int]  # on_slots minus breaks
    paid_min: int
    wage_units: int  # wage + daily OT premium, objective units
    daily_ot_min: int
    pref_units: int  # availability preference penalty (may be negative for preferred_on)
    pref_detail: list[tuple[str, float, float]] = field(default_factory=list)  # (kind, hours, dollars)
    is_open: bool = False
    is_close: bool = False
    weekend: bool = False

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
    meal_rule: Optional[LawRule]
    rest_rule: Optional[LawRule]
    notes: list[str]

    def law_of(self, t: LawRuleType) -> list[LawRule]:
        return [r for r in self.laws if r.type == t]

    def applies(self, c: Constraint, eid: str) -> bool:
        return c.applies_to_employee_ids is None or eid in c.applies_to_employee_ids

    def minor_rules(self, e: Employee) -> list[LawRule]:
        return [r for r in self.law_of(LawRuleType.minor_limits)
                if r.params.get("age_min", 0) <= e.age <= r.params.get("age_max", -1)]

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


def place_breaks(p: Prep, start: int, length: int) -> Optional[list[Break]]:
    """Deterministic breaks for a shift [start, start+length). None if they cannot fit."""
    s = p.slot
    end = start + length
    taken: list[tuple[int, int]] = []
    out: list[Break] = []

    def free(a: int, b: int) -> bool:
        return a >= start + s and b <= end - s and all(b <= x or a >= y for x, y in taken)

    m = p.meal_rule
    if m is not None and length > int(m.params["after_minutes"]):
        dur = _round_up(int(m.params["duration"]), s)
        latest = m.params.get("latest_start_minute_of_shift")
        if latest is not None:
            bs = start + _round_down(int(latest), s)
            bs = min(bs, end - s - dur)
        else:
            bs = start + _round_down((length - dur) // 2, s)
        if not free(bs, bs + dur):
            return None
        taken.append((bs, bs + dur))
        out.append(Break(start=bs, end=bs + dur, kind="meal", paid=bool(m.params.get("paid", False))))

    r = p.rest_rule
    if r is not None:
        per = int(r.params["per_minutes_worked"])
        n = length // per if per > 0 else 0
        dur = _round_up(int(r.params["duration"]), s)
        for k in range(1, n + 1):
            target = start + _round_down(k * length // (n + 1), s)
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


def build_prep(cfg: StoreConfig, with_cands: bool = True) -> Prep:
    slot = cfg.store.slot_minutes
    laws = list(cfg.law_pack.rules) if cfg.law_pack else []
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
        meal_rule=_pick([r for r in laws if r.type == LawRuleType.meal_break],
                        lambda r: r.params["after_minutes"]),
        rest_rule=_pick([r for r in laws if r.type == LawRuleType.rest_break],
                        lambda r: r.params["per_minutes_worked"]),
        notes=notes,
    )

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
                if e.age < lr.params["age_below"] and set(cfg.role_tags.get(rid, [])) & set(lr.params["role_tags"]):
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

    # Candidate shifts
    for e in (cfg.employees if with_cands else []):
        if not p.allowed_roles[e.id]:
            continue
        lo, hi = p.shift_bounds(e.id)
        minors = p.minor_rules(e)
        earliest = max([r.params["earliest_start"] for r in minors if r.params.get("earliest_start") is not None],
                       default=None)
        latest_end = min([r.params["latest_end"] for r in minors if r.params.get("latest_end") is not None],
                         default=None)
        max_day_min = min([int(r.params["max_hours_day"] * 60) for r in minors
                           if r.params.get("max_hours_day") is not None], default=None)
        week_cap = min(c for c, _, _ in p.effective_max_minutes(e))
        for day, (w0, w1) in sorted(windows.items()):
            avail = list(_avail_for_day(p, e, day))
            unavail = [(a.start, a.end) for a in avail if a.kind == AvailabilityKind.unavailable]
            o, c = store_open[day]
            lst = p.by_emp_day.setdefault((e.id, day), [])
            for start in range(_round_up(w0, slot), w1, slot):
                if earliest is not None and start < earliest:
                    continue
                for length in range(lo, hi + 1, slot):
                    end = start + length
                    if end > w1:
                        break
                    if latest_end is not None and end > latest_end:
                        break
                    if any(a < end and start < b for a, b in unavail):
                        continue
                    brks = place_breaks(p, start, length)
                    if brks is None:
                        continue
                    unpaid = sum(b.end - b.start for b in brks if not b.paid)
                    paid = length - unpaid
                    if paid > week_cap:
                        continue
                    if max_day_min is not None and paid > max_day_min:
                        continue
                    daily_ot = 0
                    if p.daily_ot is not None:
                        thr = int(p.daily_ot.params["threshold_hours"] * 60)
                        if paid > thr:
                            if not cfg.budget.overtime_allowed:
                                continue
                            daily_ot = paid - thr
                    wage = paid / 60 * e.wage_per_hour
                    if daily_ot:
                        wage += daily_ot / 60 * e.wage_per_hour * (p.daily_ot.params["multiplier"] - 1)
                        dbl = p.daily_ot.params.get("double_threshold_hours")
                        if dbl is not None and paid > dbl * 60:
                            wage += (paid - dbl * 60) / 60 * e.wage_per_hour * (2 - p.daily_ot.params["multiplier"])
                    pref, detail = 0.0, []
                    for a in avail:
                        if a.kind == AvailabilityKind.unavailable:
                            continue
                        ov = max(0, min(end, a.end) - max(start, a.start)) / 60
                        if a.kind == AvailabilityKind.preferred_off and ov > 0:
                            pref += a.weight_dollars * ov
                            detail.append(("preferred_off", ov, a.weight_dollars * ov))
                        elif a.kind == AvailabilityKind.preferred_on:
                            pref -= a.weight_dollars * ov  # constant added in model
                    bset = [(b.start, b.end) for b in brks]
                    on = [day * DAY + t for t in range(start, end, slot)]
                    work = [day * DAY + t for t in range(start, end, slot)
                            if not any(x <= t < y for x, y in bset)]
                    cand = Cand(
                        idx=len(p.cands), emp=e.id, day=day, start=start, end=end, breaks=brks,
                        on_slots=on, work_slots=work, paid_min=paid, wage_units=money(wage),
                        daily_ot_min=daily_ot, pref_units=money(pref), pref_detail=detail,
                        is_open=start < o, is_close=end > c, weekend=day in (5, 6),
                    )
                    p.cands.append(cand)
                    lst.append(cand)
    return p
