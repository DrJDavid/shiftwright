"""Gap explanations: one factual GapReason per employee TRAINED for the gap's role.

Every reason is derived from the config and the schedule (never guessed):
  1. minor_rule      the role is blocked for this employee by law (minor_prohibited_roles) or role.min_age
  2. unavailable     an `unavailable` window overlaps the gap
  3. on shift during the gap:
       law_rule        on a legally required break during the gap (law_rule_id = the break rule)
       already_assigned working (another or the same) role during the gap
  4. minor_rule      minor time-of-day limit excludes the gap, or minor weekly/daily hours are used up
  5. rest_rule       a shift the day before/after leaves too little rest to cover the gap
  6. at_max_hours    weekly hour cap reached (max_hours_week / OT threshold) or max days per week reached
  7. budget_cap      the store's weekly hours budget is used up
  8. cheaper_to_leave_gap   otherwise
"""
from __future__ import annotations

from shiftwright_contracts.models import (
    AvailabilityKind,
    ConstraintKind,
    Gap,
    GapReason,
    GapReasonCode,
    LawRuleType,
    Schedule,
    StoreConfig,
    Strength,
)

from .output import paid_minutes
from .prep import DAY, Prep, _avail_for_day, build_prep


def explain_gap(config: StoreConfig, schedule: Schedule, gap: Gap) -> list[GapReason]:
    return explain_with_prep(build_prep(config, with_cands=False), schedule, gap)


def explain_with_prep(p: Prep, schedule: Schedule, gap: Gap) -> list[GapReason]:
    cfg = p.cfg
    by_ed = {(s.employee_id, s.day): s for s in schedule.shifts}
    week_min: dict[str, int] = {}
    days_worked: dict[str, int] = {}
    for s in schedule.shifts:
        week_min[s.employee_id] = week_min.get(s.employee_id, 0) + paid_minutes(s)
        days_worked[s.employee_id] = days_worked.get(s.employee_id, 0) + 1
    total_min = sum(week_min.values())
    cap_min = (cfg.budget.weekly_hours_cap + sum(a.extra_hours for a in cfg.budget.approvals)) * 60
    g0, g1 = gap.day * DAY + gap.start, gap.day * DAY + gap.end
    slot = p.slot

    rest_rules = []
    for c in p.constraints:
        if c.kind == ConstraintKind.min_rest_between_shifts and c.strength == Strength.hard:
            rest_rules.append((int(c.params["minutes"]), c.id, None, c))
    for lr in p.law_of(LawRuleType.min_rest_between_shifts):
        rest_rules.append((int(lr.params["minutes"]), None, lr.id, None))
    max_days = [c for c in p.constraints if c.kind == ConstraintKind.max_days_per_week and c.strength == Strength.hard]

    out: list[GapReason] = []
    for e in cfg.employees:
        if gap.role_id not in e.trained_role_ids:
            continue
        R = lambda code, cid=None, lid=None: GapReason(employee_id=e.id, code=code, constraint_id=cid, law_rule_id=lid)  # noqa: E731

        blocked = p.blocked_roles.get(e.id, {}).get(gap.role_id)
        if blocked:
            out.append(R(GapReasonCode.minor_rule, lid=blocked[1]))
            continue
        if any(a.kind == AvailabilityKind.unavailable and a.start < gap.end and gap.start < a.end
               for a in _avail_for_day(p, e, gap.day)) or gap.day not in p.windows:
            out.append(R(GapReasonCode.unavailable))
            continue

        # On shift during the gap (this day, or an overnight shift from the day before)?
        on = None
        for d in (gap.day, gap.day - 1):
            s = by_ed.get((e.id, d))
            if s is not None and d * DAY + s.start < g1 and g0 < d * DAY + s.end:
                on = (d, s)
                break
        if on is not None:
            d, s = on
            working = any(d * DAY + seg.start < g1 and g0 < d * DAY + seg.end for seg in s.segments)
            if not working:
                brk = next(b for b in s.breaks if d * DAY + b.start < g1 and g0 < d * DAY + b.end)
                rules = p.meal_rules if brk.kind == "meal" else ([p.rest_rule] if p.rest_rule else [])
                out.append(R(GapReasonCode.law_rule, lid=rules[0].id if rules else None))
            else:
                out.append(R(GapReasonCode.already_assigned))
            continue

        # Minor time-of-day / hour limits
        minor = None
        for lr in p.minor_rules(e):
            pr = lr.params
            late = pr.get("latest_end")
            if pr.get("latest_end_before_non_school_day") is not None and (
                    not pr.get("school_week") or gap.day in (4, 5)):
                late = pr["latest_end_before_non_school_day"]
            if pr.get("earliest_start") is not None and gap.end <= pr["earliest_start"]:
                minor = lr.id
            elif late is not None and gap.start >= late:
                minor = lr.id
            elif pr.get("max_hours_week") is not None and week_min.get(e.id, 0) + slot > pr["max_hours_week"] * 60:
                minor = lr.id
            if minor:
                break
        if minor:
            out.append(R(GapReasonCode.minor_rule, lid=minor))
            continue

        # Rest between shifts
        rest_hit = None
        prev, nxt = by_ed.get((e.id, gap.day - 1)), by_ed.get((e.id, gap.day + 1))
        for minutes, cid, lid, con in rest_rules:
            if con is not None and not p.applies(con, e.id):
                continue
            if prev is not None and (gap.day - 1) * DAY + prev.end + minutes > g0:
                rest_hit = (cid, lid)
            if nxt is not None and g1 + minutes > (gap.day + 1) * DAY + nxt.start:
                rest_hit = (cid, lid)
            if rest_hit:
                break
        if rest_hit:
            out.append(R(GapReasonCode.rest_rule, cid=rest_hit[0], lid=rest_hit[1]))
            continue

        # Weekly caps
        capped = None
        for cap, bucket, ident in p.effective_max_minutes(e):
            if week_min.get(e.id, 0) + slot > cap:
                capped = (None, ident) if bucket == "law" else (None, None)
                break
        if capped is None:
            for c in max_days:
                if p.applies(c, e.id) and days_worked.get(e.id, 0) >= int(c.params["days"]):
                    capped = (c.id, None)
                    break
        if capped is not None:
            out.append(R(GapReasonCode.at_max_hours, cid=capped[0], lid=capped[1]))
            continue
        if total_min + slot > cap_min:
            out.append(R(GapReasonCode.budget_cap))
            continue
        out.append(R(GapReasonCode.cheaper_to_leave_gap))
    return out
