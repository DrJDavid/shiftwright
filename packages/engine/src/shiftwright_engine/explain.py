"""Gap explanations: one factual GapReason per employee TRAINED for the gap's role.

Every reason is derived from the config and the schedule (never guessed):
  1. minor_rule      the role is blocked for this employee by law (minor_prohibited_roles) or role.min_age
  2. unavailable     an `unavailable` window overlaps the gap
  3. on shift during the gap:
       law_rule        on a legally required break during the gap (law_rule_id = the break rule)
       already_assigned working (another or the same) role during the gap
  4. minor_rule      minor time-of-day limit excludes the gap, or minor weekly/daily hours are used up
  5. rest_rule       a shift the day before/after leaves too little rest to cover the gap
  6. at_max_hours    covering it would pass a cap: weekly hours (max_hours_week / OT threshold), max
                     days per week, the max shift length (extending a shift on a day they work), or
                     daily overtime when overtime is not allowed; minor_rule for a minor's daily cap
  7. budget_cap      the store's weekly hours budget can't take the added time
  8. law_rule        (with the solve's candidates) every longer shift that reaches the gap within
                     budget owes a law break that uncovers at least as much tier-weighted demand
                     as it adds (law_rule_id = the meal, else rest, rule)
  9. cheaper_to_leave_gap   otherwise (the solver left a gap it could have filled)
The added time is the least this person would need: an extension of their shift that day (at the
store's shifts-per-day limit), else a new shift of at least the minimum length.
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

from .lex import tier_weights
from .output import TICK, coverage_map, paid_minutes
from .prep import DAY, Prep, _avail_for_day, build_prep


def explain_gap(config: StoreConfig, schedule: Schedule, gap: Gap) -> list[GapReason]:
    return explain_with_prep(build_prep(config, with_cands=False), schedule, gap)


def explain_with_prep(p: Prep, schedule: Schedule, gap: Gap) -> list[GapReason]:
    cfg = p.cfg
    by_ed: dict[tuple[str, int], list] = {}  # split days (#23) have several shifts
    week_min: dict[str, int] = {}
    for s in schedule.shifts:
        by_ed.setdefault((s.employee_id, s.day), []).append(s)
        week_min[s.employee_id] = week_min.get(s.employee_id, 0) + paid_minutes(s)
    days_worked: dict[str, int] = {}
    for eid, _ in by_ed:
        days_worked[eid] = days_worked.get(eid, 0) + 1
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
    n_max = max(1, int(getattr(cfg.store, "max_shifts_per_day", 1) or 1))
    max_len_id: dict[str, str] = {}
    for e in cfg.employees:
        hard = [c for c in p.constraints if c.kind == ConstraintKind.max_shift_length
                and c.strength == Strength.hard and p.applies(c, e.id)]
        if hard:
            max_len_id[e.id] = min(hard, key=lambda c: int(c.params["minutes"])).id

    cov = w_tier = None

    def cap_week(e) -> int:
        return min((c for c, _, _ in p.effective_max_minutes(e)), default=7 * DAY)

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
            s = next((s for s in by_ed.get((e.id, d), []) if d * DAY + s.start < g1 and g0 < d * DAY + s.end), None)
            if s is not None:
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
        prev = max(by_ed.get((e.id, gap.day - 1), []), key=lambda s: s.end, default=None)
        nxt = min(by_ed.get((e.id, gap.day + 1), []), key=lambda s: s.start, default=None)
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

        # The least paid time this person would add to cover any of the gap: a longer shift on a
        # day they already work (at the shift limit for the day), else a new shift of at least the
        # minimum length. Every cap below is checked against that, not against one slot.
        mine = by_ed.get((e.id, gap.day), [])
        lo, hi = p.shift_bounds(e.id)
        ext = None
        if mine and len(mine) >= n_max:
            ext = _extension(p, e.id, gap, mine, slot)
            if ext is None or ext[1] > hi:
                out.append(R(GapReasonCode.at_max_hours, cid=max_len_id.get(e.id)))
                continue
            add = ext[0]
            # Reaching the gap adds no paid time only when the longer shift owes an unpaid meal
            # that takes back the minutes gained.
            meal = [m for m in p.meal_rules if ext[1] > int(m.params["after_minutes"])]
            if add <= 0 and meal:
                out.append(R(GapReasonCode.law_rule, lid=meal[0].id))
                continue
        else:
            add = _new_shift_paid(p, e.id, gap, slot, lo)
        capped = None
        for cap, bucket, ident in p.effective_max_minutes(e):
            if week_min.get(e.id, 0) + add > cap:
                capped = (None, ident) if bucket == "law" else (None, None)
                break
        if capped is None and ext is None:
            for c in max_days:
                if p.applies(c, e.id) and days_worked.get(e.id, 0) >= int(c.params["days"]):
                    capped = (c.id, None)
                    break
        if capped is not None:
            out.append(R(GapReasonCode.at_max_hours, cid=capped[0], lid=capped[1]))
            continue
        day_paid = sum(paid_minutes(s) for s in mine)
        minor_cap = p.minor_day_cap(e, gap.day)
        if minor_cap is not None and day_paid + add > minor_cap:
            out.append(R(GapReasonCode.minor_rule, lid=_minor_day_rule(p, e, gap.day, minor_cap)))
            continue
        if (p.daily_ot is not None and not cfg.budget.overtime_allowed
                and day_paid + add > p.daily_ot.params["threshold_hours"] * 60):
            out.append(R(GapReasonCode.at_max_hours, lid=p.daily_ot.id))
            continue
        if total_min + add > cap_min:
            out.append(R(GapReasonCode.budget_cap))
            continue
        if ext is not None and p.cands:
            if cov is None:
                cov, w_tier = coverage_map(p, schedule.shifts), tier_weights(p, with_always=False)[0]
            brk = _break_rule(p, ext[1])
            if brk is not None and not _net_gain(p, e, gap, mine, cov, w_tier,
                                                 min(cap_min - total_min, cap_week(e) - week_min.get(e.id, 0))):
                out.append(R(GapReasonCode.law_rule, lid=brk))
                continue
        out.append(R(GapReasonCode.cheaper_to_leave_gap))
    return out


def _break_rule(p: Prep, span: int) -> str | None:
    """The law break a shift of `span` clock minutes owes (meal first), if any."""
    meal = [m for m in p.meal_rules if span > int(m.params["after_minutes"])]
    if meal:
        return meal[0].id
    return p.rest_rule.id if p.rest_rule is not None else None


def _net_gain(p: Prep, e, gap: Gap, mine: list, cov, w_tier: dict, room: int) -> bool:
    """Is there a candidate for this employee-day that reaches the gap, adds at most `room` paid
    minutes, and raises tier-weighted coverage once the breaks it moves are counted (demand the
    employee would stop covering is lost)? Minute-exact at TICK resolution."""
    g0, g1 = gap.day * DAY + gap.start, gap.day * DAY + gap.end
    roles = [r for r in e.trained_role_ids if r in w_tier]
    for s in mine:
        base = gap.day * DAY
        old = {}
        for seg in s.segments:
            t = seg.start - seg.start % TICK
            while t < seg.end:
                old[base + t] = seg.role_id
                t += TICK
        for c in p.by_emp_day.get((e.id, gap.day), []):
            if not (base + c.start < g1 and g0 < base + c.end and c.start < s.end and s.start < c.end):
                continue
            if c.paid_min - paid_minutes(s) > room:
                continue
            new = set(range(base + c.start, base + c.end, TICK))
            for b in c.breaks:
                new -= set(range(base + b.start - b.start % TICK, base + b.end, TICK))
            net = 0
            for t, r in old.items():
                if t not in new and r in w_tier and cov.get((r, t), 0) <= p.demand.get((r, t - t % p.slot), 0):
                    net -= w_tier[r]
            for t in new:
                if t in old:
                    continue
                net += max((w_tier[r] for r in roles
                            if cov.get((r, t), 0) < p.demand.get((r, t - t % p.slot), 0)), default=0)
            if net > 0:
                return True
    return False


def _minor_day_rule(p: Prep, e, day: int, cap: int):
    for r in p.minor_rules(e):
        pr = r.params
        v = pr.get("max_hours_day")
        if pr.get("school_week") and day >= 5 and pr.get("max_hours_non_school_day") is not None:
            v = pr["max_hours_non_school_day"]
        if v is not None and int(round(v * 60)) == cap:
            return r.id
    return None


def _extension(p: Prep, eid: str, gap: Gap, mine: list, slot: int) -> tuple[int, int] | None:
    """(added paid minutes, new clock span) of the smallest extension of one of `mine` that reaches
    the gap. Uses the solve's candidate shifts when present (exact paid minutes), else clock time."""
    best = None
    cands = p.by_emp_day.get((eid, gap.day), []) if p.cands else []
    for s in mine:
        if gap.start >= s.end:
            new = (s.start, -(-(gap.start + 1) // slot) * slot)
        elif gap.end <= s.start:
            new = ((gap.end - 1) // slot * slot, s.end)
        else:
            continue
        paid_now = paid_minutes(s)
        opts = [c.paid_min - paid_now for c in cands if c.start <= new[0] and c.end >= new[1]
                and c.start <= s.start and c.end >= s.end]
        add = min(opts) if opts else (new[1] - new[0]) - (s.end - s.start)
        span = new[1] - new[0]
        if best is None or (add, span) < best:
            best = (add, span)
    return best


def _new_shift_paid(p: Prep, eid: str, gap: Gap, slot: int, lo: int) -> int:
    """Least paid minutes of a new shift covering part of the gap (the solve's candidates when
    present, else the minimum shift length)."""
    g0, g1 = gap.day * DAY + gap.start, gap.day * DAY + gap.end
    opts = [c.paid_min for c in p.by_emp_day.get((eid, gap.day), []) if p.cands
            and any(g0 < a + slot and a < g1 for a in c.work_slots)]
    return min(opts) if opts else lo
