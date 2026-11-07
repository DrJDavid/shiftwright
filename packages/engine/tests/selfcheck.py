"""A small, independent hard-rule checker used by engine tests until WS2's validator lands.

Written from the contracts only (does not import engine internals).
"""
from __future__ import annotations

from collections import defaultdict

from shiftwright_contracts.models import (
    ConstraintKind,
    LawRuleType,
    RuleStatus,
    Schedule,
    StoreConfig,
    Strength,
)


def _paid_minutes(sh) -> int:
    return (sh.end - sh.start) - sum(b.end - b.start for b in sh.breaks if not b.paid)


def hard_problems(cfg: StoreConfig, s: Schedule) -> list[str]:
    out: list[str] = []
    slot = cfg.store.slot_minutes
    emps = {e.id: e for e in cfg.employees}
    roles = {r.id: r for r in cfg.roles}
    hours = {h.day: h for h in cfg.store.hours}
    laws = cfg.law_pack.rules if cfg.law_pack else []
    per_emp_day = defaultdict(int)
    week_min = defaultdict(int)
    total_min = 0
    for sh in s.shifts:
        e = emps.get(sh.employee_id)
        if e is None:
            out.append(f"unknown employee {sh.employee_id}")
            continue
        per_emp_day[(e.id, sh.day)] += 1
        for t in (sh.start, sh.end):
            if t % slot:
                out.append(f"{sh.id} off-grid")
        h = hours.get(sh.day)
        if h is None or sh.start < h.open - cfg.store.pre_open_minutes or sh.end > h.close + cfg.store.post_close_minutes:
            out.append(f"{sh.id} outside store window")
        # tiling
        pieces = sorted([(b.start, b.end) for b in sh.breaks] + [(g.start, g.end) for g in sh.segments])
        cur = sh.start
        for a, b in pieces:
            if a != cur or b <= a:
                out.append(f"{sh.id} malformed tiling at {a}")
            cur = b
        if cur != sh.end:
            out.append(f"{sh.id} tiling ends at {cur} != {sh.end}")
        for g in sh.segments:
            if g.role_id not in e.trained_role_ids:
                out.append(f"{sh.id} not trained {g.role_id}")
            if e.age < roles[g.role_id].min_age:
                out.append(f"{sh.id} under min_age {g.role_id}")
            for lr in laws:
                if lr.type == LawRuleType.minor_prohibited_roles and e.age < lr.params["age_below"]:
                    if set(cfg.role_tags.get(g.role_id, [])) & set(lr.params["role_tags"]):
                        out.append(f"{sh.id} minor prohibited {g.role_id}")
        length = sh.end - sh.start
        for c in cfg.constraints:
            if c.status != RuleStatus.confirmed or c.strength != Strength.hard:
                continue
            if c.applies_to_employee_ids is not None and e.id not in c.applies_to_employee_ids:
                continue
            if c.kind == ConstraintKind.min_shift_length and length < c.params["minutes"]:
                out.append(f"{sh.id} too short")
            if c.kind == ConstraintKind.max_shift_length and length > c.params["minutes"]:
                out.append(f"{sh.id} too long")
        for lr in laws:
            if lr.type == LawRuleType.meal_break and length > lr.params["after_minutes"]:
                if not any(b.kind == "meal" and b.end - b.start >= lr.params["duration"] for b in sh.breaks):
                    out.append(f"{sh.id} missing meal")
            if lr.type == LawRuleType.minor_limits and lr.params["age_min"] <= e.age <= lr.params["age_max"]:
                if lr.params.get("latest_end") is not None and sh.end > lr.params["latest_end"]:
                    out.append(f"{sh.id} minor latest_end")
                cap = lr.params.get("max_hours_day")
                if lr.params.get("school_week") and sh.day >= 5 and lr.params.get("max_hours_non_school_day") is not None:
                    cap = lr.params["max_hours_non_school_day"]  # Sat/Sun are non-school days
                if cap is not None and _paid_minutes(sh) > cap * 60:
                    out.append(f"{sh.id} minor hours/day")
        for a in e.availability:
            if a.kind.value == "unavailable" and a.weekday == sh.day and a.start < sh.end and sh.start < a.end:
                out.append(f"{sh.id} unavailable")
        pm = _paid_minutes(sh)
        week_min[e.id] += pm
        total_min += pm
    for k, n in per_emp_day.items():
        if n > 1:
            out.append(f"{k} has {n} shifts")
    for eid, m in week_min.items():
        if m > emps[eid].max_hours_week * 60 + 1e-6:
            out.append(f"{eid} over max hours")
    cap = cfg.budget.weekly_hours_cap + sum(a.extra_hours for a in cfg.budget.approvals)
    if total_min > cap * 60 + 1e-6:
        out.append("over budget hours")
    if s.metrics and abs(s.metrics.total_hours - total_min / 60) > 0.01:
        out.append("metrics total_hours mismatch")
    return out
