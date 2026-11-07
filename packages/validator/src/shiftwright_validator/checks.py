"""One check function per ViolationCode. Each takes the Context (+ recomputed numbers) and
returns a list of Violations. Plain loops; clarity over speed."""
from __future__ import annotations

from datetime import date

from shiftwright_contracts.models import (
    BREAK_GRANULARITY_MINUTES,
    ROLE_TAGS,
    ConstraintKind,
    LawRuleType,
    RuleStatus,
    Strength,
    Violation,
    ViolationCode,
)

from .common import (
    as_float,
    as_int,
    day_name,
    fmt_time,
    is_tipped_shift,
    law_rules,
    overlap_minutes,
    shift_interval,
    shifts_by_employee,
    span_minutes,
)
from .context import Context, structural_problems
from .measure import MEASURES, rest_shortfalls
from .metrics import Computed
from .soft import availability_windows

C = ViolationCode
EPS = 1e-6


def hard(code: ViolationCode, message: str, **kw) -> Violation:
    return Violation(code=code, severity="hard", message=message, **kw)


def where(shift) -> str:
    return f"shift {shift.id} ({shift.employee_id}, {day_name(shift.day)} " \
           f"{fmt_time(shift.start)}-{fmt_time(shift.end)})"


def at(shift) -> dict:
    return dict(employee_id=shift.employee_id, day=shift.day, start=shift.start, end=shift.end)


def hard_constraints_of(ctx: Context, kind: ConstraintKind):
    return [c for c in ctx.config.constraints
            if c.kind == kind and c.status == RuleStatus.confirmed and c.strength == Strength.hard]


def from_measure(ctx: Context, kind: ConstraintKind, code: ViolationCode) -> list[Violation]:
    out = []
    for c in hard_constraints_of(ctx, kind):
        for f in MEASURES[kind](ctx, c):
            out.append(hard(code, f.message, employee_id=f.employee_id, role_id=f.role_id,
                            day=f.day, start=f.start, end=f.end, constraint_id=c.id))
    return out


# --------------------------------------------------------------------------- #
# Shape of the schedule
# --------------------------------------------------------------------------- #
def check_malformed(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    schedule = ctx.schedule
    slot = ctx.slot
    if schedule.week_start != ctx.config.store.week_start:
        out.append(hard(C.malformed, f"Schedule week_start {schedule.week_start} does not match "
                                     f"the store's week {ctx.config.store.week_start}."))
    shifts = schedule.shifts if isinstance(schedule.shifts, list) else []
    if not isinstance(schedule.shifts, list):
        out.append(hard(C.malformed, "Schedule shifts is not a list."))
    # SEMANTICS #21: a role tag outside ROLE_TAGS could silently disable a law, so it's malformed.
    for role_id, tags in sorted(ctx.config.role_tags.items()):
        for tag in tags:
            if tag not in ROLE_TAGS:
                out.append(hard(C.malformed, f"Role {role_id!r} has unknown tag {tag!r}; tags must come "
                                             f"from ROLE_TAGS.", role_id=role_id))

    seen_ids: set = set()
    for i, shift in enumerate(shifts):
        sid = getattr(shift, "id", None)
        if sid in seen_ids:
            out.append(hard(C.malformed, f"Shift id {sid!r} is used more than once."))
        seen_ids.add(sid)

        problems = structural_problems(shift)
        if problems:
            out.append(hard(C.malformed, f"Shift #{i} ({sid!r}) is unusable: " + "; ".join(problems)
                            + ". It is ignored by every other check.",
                            employee_id=getattr(shift, "employee_id", None)
                            if isinstance(getattr(shift, "employee_id", None), str) else None))
            continue

        def bad(msg: str):
            out.append(hard(C.malformed, f"{where(shift)}: {msg}", **at(shift)))

        if shift.start % slot or shift.end % slot:
            bad(f"times are not on the {slot}-minute grid.")

        # breaks: positive length, inside the shift, on the grid, not overlapping each other
        break_minutes: set[int] = set()
        for brk in shift.breaks:
            if brk.end <= brk.start:
                bad(f"{brk.kind} break {fmt_time(brk.start)}-{fmt_time(brk.end)} has no length.")
                continue
            if brk.start < shift.start or brk.end > shift.end:
                bad(f"{brk.kind} break {fmt_time(brk.start)}-{fmt_time(brk.end)} is outside the shift.")
            if brk.start % BREAK_GRANULARITY_MINUTES or brk.end % BREAK_GRANULARITY_MINUTES:
                bad(f"{brk.kind} break {fmt_time(brk.start)}-{fmt_time(brk.end)} is not on the "
                    f"{BREAK_GRANULARITY_MINUTES}-minute break grid.")
            minutes = set(range(max(brk.start, shift.start), min(brk.end, shift.end)))
            if minutes & break_minutes:
                bad("breaks overlap each other.")
            break_minutes |= minutes

        # segments must tile [start, end) minus breaks exactly, without overlaps
        # a segment edge may sit on the 5-minute break grid only where it touches a break
        break_edges = {b.start for b in shift.breaks} | {b.end for b in shift.breaks}

        def edge_ok(t: int) -> bool:
            return t % slot == 0 or (t % BREAK_GRANULARITY_MINUTES == 0 and t in break_edges)

        covered: set[int] = set()
        tiling_ok = True
        for seg in shift.segments:
            if seg.end <= seg.start:
                bad(f"segment {seg.role_id} {fmt_time(seg.start)}-{fmt_time(seg.end)} has no length.")
                tiling_ok = False
                continue
            if not edge_ok(seg.start) or not edge_ok(seg.end):
                bad(f"segment {seg.role_id} {fmt_time(seg.start)}-{fmt_time(seg.end)} is off the grid "
                    f"(only edges touching a break may use the {BREAK_GRANULARITY_MINUTES}-minute grid).")
            if seg.start < shift.start or seg.end > shift.end:
                bad(f"segment {seg.role_id} {fmt_time(seg.start)}-{fmt_time(seg.end)} is outside the shift.")
                tiling_ok = False
            # clip to the shift so absurd times can't build huge sets
            minutes = set(range(max(seg.start, shift.start), min(seg.end, shift.end)))
            if minutes & covered:
                bad("role segments overlap each other.")
                tiling_ok = False
            covered |= minutes
        if tiling_ok:
            work = set(range(shift.start, shift.end)) - break_minutes
            if covered != work:
                missing = len(work - covered)
                extra = len(covered - work)
                bad(f"role segments don't tile the shift minus breaks "
                    f"({missing} min uncovered, {extra} min outside work time).")
    return out


def check_unknown_entity(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    if ctx.schedule.store_id != ctx.config.store.id:
        out.append(hard(C.unknown_entity, f"Schedule is for store {ctx.schedule.store_id!r}, "
                                          f"not {ctx.config.store.id!r}."))
    for shift in ctx.structurally_ok:
        if shift.employee_id not in ctx.employees:
            out.append(hard(C.unknown_entity,
                            f"{where(shift)}: employee {shift.employee_id!r} does not exist.", **at(shift)))
        for seg in shift.segments:
            if seg.role_id not in ctx.roles:
                out.append(hard(C.unknown_entity, f"{where(shift)}: role {seg.role_id!r} does not exist.",
                                role_id=seg.role_id, **at(shift)))
    return out


# --------------------------------------------------------------------------- #
# Who works what, when
# --------------------------------------------------------------------------- #
def check_not_trained(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    for shift in ctx.usable:
        trained = ctx.employees[shift.employee_id].trained_role_ids
        flagged: set[str] = set()
        for seg in shift.segments:
            if seg.role_id in ctx.roles and seg.role_id not in trained and seg.role_id not in flagged:
                flagged.add(seg.role_id)
                out.append(hard(C.not_trained, f"{where(shift)}: not trained for {seg.role_id}.",
                                role_id=seg.role_id, **at(shift)))
    return out


def check_unavailable(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    for shift in ctx.usable:
        employee = ctx.employees[shift.employee_id]
        s_start, s_end = shift_interval(shift)
        for entry, w_start, w_end in availability_windows(ctx, employee):
            if entry.kind.value != "unavailable":
                continue
            if overlap_minutes(s_start, s_end, w_start, w_end) > 0:
                day = w_start // 1440
                out.append(hard(C.unavailable,
                                f"{where(shift)}: overlaps unavailable window {day_name(day)} "
                                f"{fmt_time(entry.start)}-{fmt_time(entry.end)}.", **at(shift)))
    return out


def check_double_booked(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    for employee_id, shifts in shifts_by_employee(ctx.usable).items():
        for i, a in enumerate(shifts):
            for b in shifts[i + 1:]:
                if overlap_minutes(*shift_interval(a), *shift_interval(b)) > 0:
                    out.append(hard(C.double_booked,
                                    f"{employee_id} is in two places at once: shift {a.id} and shift {b.id}.",
                                    **at(b)))
    return out


def check_shifts_per_day(ctx: Context, computed: Computed) -> list[Violation]:
    """SEMANTICS #23: at most Store.max_shifts_per_day shifts per employee per day (by start day)."""
    limit = ctx.config.store.max_shifts_per_day
    counts: dict[tuple[str, int], int] = {}
    for shift in ctx.usable:
        key = (shift.employee_id, shift.day)
        counts[key] = counts.get(key, 0) + 1
    return [hard(C.shifts_per_day, f"{eid} has {n} shifts on {day_name(day)}; the store allows {limit}.",
                 employee_id=eid, day=day)
            for (eid, day), n in sorted(counts.items()) if n > limit]


def check_outside_store_window(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    store = ctx.config.store
    for shift in ctx.usable:
        hours = next((h for h in store.hours if h.day == shift.day), None)
        if hours is None:
            out.append(hard(C.outside_store_window,
                            f"{where(shift)}: the store has no hours on {day_name(shift.day)}.", **at(shift)))
            continue
        earliest = hours.open - store.pre_open_minutes
        latest = hours.close + store.post_close_minutes
        if shift.start < earliest or shift.end > latest:
            out.append(hard(C.outside_store_window,
                            f"{where(shift)}: staff may only work {fmt_time(earliest)}-{fmt_time(latest)}.",
                            **at(shift)))
    return out


# --------------------------------------------------------------------------- #
# Hours, rest, days
# --------------------------------------------------------------------------- #
def check_max_hours_week(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    for employee_id, hours in computed.paid_hours_by_employee.items():
        limit = ctx.employees[employee_id].max_hours_week
        if hours > limit + EPS:
            out.append(hard(C.max_hours_week, f"{employee_id} is scheduled {hours:g} h; max is {limit:g} h.",
                            employee_id=employee_id))
    return out


def check_shift_length(ctx: Context, computed: Computed) -> list[Violation]:
    return (from_measure(ctx, ConstraintKind.min_shift_length, C.shift_length)
            + from_measure(ctx, ConstraintKind.max_shift_length, C.shift_length))


def check_rest_between_shifts(ctx: Context, computed: Computed) -> list[Violation]:
    out = from_measure(ctx, ConstraintKind.min_rest_between_shifts, C.rest_between_shifts)
    # Law rules without a premium are hard; with a premium they are priced in premium_pay_dollars.
    for rule in law_rules(ctx.config, LawRuleType.min_rest_between_shifts):
        if as_float(rule.params.get("premium_multiplier")) is not None:
            continue
        minutes = as_int(rule.params.get("minutes"), 0)
        if minutes <= 0:
            continue
        same_day = not rule.params.get("excludes_same_day_split")
        for f in rest_shortfalls(ctx, minutes, same_day=same_day):
            out.append(hard(C.rest_between_shifts, f.message + f" ({rule.summary})",
                            employee_id=f.employee_id, day=f.day, start=f.start, end=f.end,
                            law_rule_id=rule.id))
    return out


def check_days_per_week(ctx: Context, computed: Computed) -> list[Violation]:
    return from_measure(ctx, ConstraintKind.max_days_per_week, C.days_per_week)


def check_consecutive_days(ctx: Context, computed: Computed) -> list[Violation]:
    return from_measure(ctx, ConstraintKind.max_consecutive_days, C.consecutive_days)


# --------------------------------------------------------------------------- #
# Budget and overtime
# --------------------------------------------------------------------------- #
def check_budget_hours(ctx: Context, computed: Computed) -> list[Violation]:
    m = computed.metrics
    if m.budget_hours_used > m.budget_hours_cap + EPS:
        return [hard(C.budget_hours, f"Schedule uses {m.budget_hours_used:g} h; the cap (with approvals) "
                                     f"is {m.budget_hours_cap:g} h.")]
    return []


def check_budget_dollars(ctx: Context, computed: Computed) -> list[Violation]:
    budget = ctx.config.budget
    if budget.weekly_dollar_cap is None:
        return []
    cap = budget.weekly_dollar_cap + sum(a.extra_dollars for a in budget.approvals)
    spent = computed.metrics.total_wage_cost + computed.metrics.premium_pay_dollars
    if spent > cap + 0.005:
        return [hard(C.budget_dollars, f"Labor cost ${spent:,.2f} (wages + premiums) exceeds the "
                                       f"dollar cap ${cap:,.2f}.")]
    return []


def check_overtime_not_allowed(ctx: Context, computed: Computed) -> list[Violation]:
    if ctx.config.budget.overtime_allowed:
        return []
    out = []
    for employee_id, ot in computed.overtime_by_employee.items():
        if ot.overtime_hours > EPS:
            out.append(hard(C.overtime_not_allowed,
                            f"{employee_id} works {ot.overtime_hours:g} h of overtime; overtime is not allowed.",
                            employee_id=employee_id))
    return out


# --------------------------------------------------------------------------- #
# Breaks (law pack)
# --------------------------------------------------------------------------- #
def check_meal_break(ctx: Context, computed: Computed) -> list[Violation]:
    # One rule per after_minutes threshold; if two share a threshold keep the longer break.
    by_threshold: dict[int, object] = {}
    for rule in law_rules(ctx.config, LawRuleType.meal_break):
        after = as_int(rule.params.get("after_minutes"), -1)
        if after < 0:
            continue
        kept = by_threshold.get(after)
        if kept is None or as_int(rule.params.get("duration")) > as_int(kept.params.get("duration")):
            by_threshold[after] = rule
    rules = [by_threshold[k] for k in sorted(by_threshold)]

    out = []
    for shift in ctx.usable:
        length = span_minutes(shift)
        required = []
        for rule in rules:
            waivable = as_int(rule.params.get("waivable_under_minutes"), -1)
            if length > as_int(rule.params.get("after_minutes")) and not (waivable >= 0 and length <= waivable):
                required.append(rule)
        meals = sorted((b for b in shift.breaks if b.kind == "meal"), key=lambda b: b.start)
        for k, rule in enumerate(required):
            duration = as_int(rule.params.get("duration"))
            adequate = [b for b in meals if b.end - b.start >= duration
                        and b.start >= shift.start and b.end <= shift.end]
            if len(adequate) <= k:
                out.append(hard(C.meal_break, f"{where(shift)}: a {length}-min shift needs meal break "
                                              f"#{k + 1} of {duration} min. {rule.summary}",
                                law_rule_id=rule.id, **at(shift)))
                continue
            latest = rule.params.get("latest_start_minute_of_shift")
            if latest is not None and adequate[k].start - shift.start > as_int(latest):
                out.append(hard(C.meal_break, f"{where(shift)}: meal break #{k + 1} starts "
                                              f"{adequate[k].start - shift.start} min into the shift; "
                                              f"latest allowed is {as_int(latest)} min. {rule.summary}",
                                law_rule_id=rule.id, **at(shift)))
    return out


def check_rest_break(ctx: Context, computed: Computed) -> list[Violation]:
    rules = law_rules(ctx.config, LawRuleType.rest_break)
    out = []
    for shift in ctx.usable:
        length = span_minutes(shift)
        for rule in rules:
            per = as_int(rule.params.get("per_minutes_worked"), 0)
            if per <= 0:
                continue
            needed = length // per
            # WS3 extra key: below this length no rest break is due; at or above it at least one is.
            not_under = rule.params.get("not_required_under_minutes")
            if not_under is not None:
                needed = 0 if length < as_int(not_under) else max(needed, 1)
            duration = as_int(rule.params.get("duration"))
            have = sum(1 for b in shift.breaks if b.kind == "rest" and b.end - b.start >= duration
                       and b.start >= shift.start and b.end <= shift.end)
            if have < needed:
                out.append(hard(C.rest_break, f"{where(shift)}: a {length}-min shift needs {needed} rest "
                                              f"break(s) of {duration} min; has {have}. {rule.summary}",
                                law_rule_id=rule.id, **at(shift)))
    return out


# --------------------------------------------------------------------------- #
# Minors
# --------------------------------------------------------------------------- #
NON_SCHOOL_DAYS = (5, 6)               # Sat, Sun
BEFORE_NON_SCHOOL_DAY = (4, 5)         # Fri, Sat nights


def day_limit(params: dict, day: int) -> float | None:
    """Daily hours cap for a minor_limits rule on `day`."""
    if params.get("school_week") and day in NON_SCHOOL_DAYS \
            and params.get("max_hours_non_school_day") is not None:
        return as_float(params.get("max_hours_non_school_day"))
    return as_float(params.get("max_hours_day"))


def latest_end(params: dict, day: int) -> int | None:
    """Latest allowed shift end for a minor_limits rule on `day`."""
    late = params.get("latest_end_before_non_school_day")
    if late is not None and (not params.get("school_week") or day in BEFORE_NON_SCHOOL_DAY):
        return as_int(late)
    if params.get("latest_end") is None:
        return None
    return as_int(params.get("latest_end"))


def minor_rule_applies(params: dict, school_week) -> bool:
    """SEMANTICS #8: Store.school_week None = every rule, True = school-week rules only,
    False = non-school rules only. A rule without a school_week key applies either way."""
    rule_flag = params.get("school_week")
    if school_week is None or rule_flag is None:
        return True
    return bool(rule_flag) == school_week


def check_minor_hours(ctx: Context, computed: Computed) -> list[Violation]:
    """Applies the minor_limits rules matching the employee's age, filtered by Store.school_week
    (SEMANTICS #8). Within a school week, Mon-Fri are school days and Sat/Sun are not; WS3's extra
    keys `max_hours_non_school_day` and `latest_end_before_non_school_day` use that."""
    out = []
    school_week = ctx.config.store.school_week
    for rule in law_rules(ctx.config, LawRuleType.minor_limits):
        p = rule.params
        if not minor_rule_applies(p, school_week):
            continue
        age_min, age_max = as_int(p.get("age_min"), 0), as_int(p.get("age_max"), -1)
        max_week = as_float(p.get("max_hours_week"))
        earliest = p.get("earliest_start")
        for employee in ctx.config.employees:
            if not age_min <= employee.age <= age_max:
                continue
            eid = employee.id

            def flag(msg, **kw):
                out.append(hard(C.minor_hours, f"{eid} (age {employee.age}): {msg} {rule.summary}",
                                employee_id=eid, law_rule_id=rule.id, **kw))

            if max_week is not None:
                hours = computed.paid_hours_by_employee.get(eid, 0.0)
                if hours > max_week + EPS:
                    flag(f"{hours:g} h this week; limit {max_week:g} h.")
            for (e, day), hours in sorted(computed.paid_hours_by_employee_day.items()):
                limit = day_limit(p, day)
                if e == eid and limit is not None and hours > limit + EPS:
                    flag(f"{hours:g} h on {day_name(day)}; limit {limit:g} h.", day=day)
            for shift in ctx.usable:
                if shift.employee_id != eid:
                    continue
                if earliest is not None and shift.start < as_int(earliest):
                    flag(f"starts {fmt_time(shift.start)}, earliest allowed {fmt_time(as_int(earliest))}.",
                         day=shift.day, start=shift.start, end=shift.end)
                latest_today = latest_end(p, shift.day)
                if latest_today is not None and shift.end > latest_today:
                    flag(f"works until {fmt_time(shift.end)}, latest allowed {fmt_time(latest_today)}.",
                         day=shift.day, start=shift.start, end=shift.end)
    return out


def check_minor_prohibited_role(ctx: Context, computed: Computed) -> list[Violation]:
    rules = law_rules(ctx.config, LawRuleType.minor_prohibited_roles)
    out = []
    for shift in ctx.usable:
        employee = ctx.employees[shift.employee_id]
        flagged: set[str] = set()
        for seg in shift.segments:
            role = ctx.roles.get(seg.role_id)
            if role is None or seg.role_id in flagged:
                continue
            tags = set(ctx.config.role_tags.get(seg.role_id, []))
            hit = None
            for rule in rules:
                banned = rule.params.get("role_tags") or []
                lowest = as_int(rule.params.get("age_min"), 0)  # v1.5: null = no lower bound
                if lowest <= employee.age < as_int(rule.params.get("age_below"), 0) and tags & set(banned):
                    hit = rule
                    break
            if hit is not None:
                flagged.add(seg.role_id)
                out.append(hard(C.minor_prohibited_role,
                                f"{where(shift)}: age {employee.age} may not work {seg.role_id}. {hit.summary}",
                                role_id=seg.role_id, law_rule_id=hit.id, **at(shift)))
            elif employee.age < role.min_age:
                flagged.add(seg.role_id)
                out.append(hard(C.minor_prohibited_role,
                                f"{where(shift)}: {seg.role_id} requires age {role.min_age}; "
                                f"employee is {employee.age}.", role_id=seg.role_id, **at(shift)))
    return out


# --------------------------------------------------------------------------- #
# Minimum wage
# --------------------------------------------------------------------------- #
def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def wage_floor_rule(ctx: Context, rule_type: LawRuleType, key: str):
    """The rule of `rule_type` in effect on week_start (SEMANTICS #15): per jurisdiction the latest
    one already effective, then the highest `key` of those. A rule without a readable date counts as
    in effect. Returns (dollars, rule) or None."""
    week_start = ctx.config.store.week_start
    latest: dict[tuple, tuple] = {}  # jurisdiction key -> (effective, dollars, rule)
    for rule in law_rules(ctx.config, rule_type):
        dollars = as_float(rule.params.get(key))
        if dollars is None:
            continue
        effective = _as_date(rule.params.get("effective")) or date.min
        if effective > week_start:
            continue
        jkey = (rule.level, rule.jurisdiction.state, rule.jurisdiction.city)
        if jkey not in latest or effective > latest[jkey][0]:
            latest[jkey] = (effective, dollars, rule)
    if not latest:
        return None
    _, dollars, rule = max(latest.values(), key=lambda x: x[1])
    return dollars, rule


def minimum_wage_rule(ctx: Context):
    return wage_floor_rule(ctx, LawRuleType.minimum_wage, "dollars_per_hour")


def check_below_minimum_wage(ctx: Context, computed: Computed) -> list[Violation]:
    full = minimum_wage_rule(ctx)
    # #15 v1.5: tipped cash wage vs tipped_minimum_wage; without such a rule the full minimum applies.
    tipped = wage_floor_rule(ctx, LawRuleType.tipped_minimum_wage, "cash_wage_per_hour") or full
    out = []
    scheduled = sorted({s.employee_id for s in ctx.usable})
    for employee_id in scheduled:
        employee = ctx.employees[employee_id]
        if full is not None and employee.wage_per_hour < full[0] - EPS:
            out.append(hard(C.below_minimum_wage,
                            f"{employee_id} is paid ${employee.wage_per_hour:,.2f}/h; minimum wage is "
                            f"${full[0]:,.2f}/h. {full[1].summary}",
                            employee_id=employee_id, law_rule_id=full[1].id))
        has_tipped_shift = any(s.employee_id == employee_id and is_tipped_shift(s, employee, ctx.roles)
                               for s in ctx.usable)
        if tipped is not None and has_tipped_shift and employee.tipped_wage_per_hour < tipped[0] - EPS:
            which = "tipped minimum cash wage" if tipped is not full else \
                "minimum wage (no tip credit in the law pack)"
            out.append(hard(C.below_minimum_wage,
                            f"{employee_id}'s tipped cash wage is ${employee.tipped_wage_per_hour:,.2f}/h; "
                            f"{which} is ${tipped[0]:,.2f}/h. {tipped[1].summary}",
                            employee_id=employee_id, law_rule_id=tipped[1].id))
    return out


# --------------------------------------------------------------------------- #
# Store rules, metrics, soft costs
# --------------------------------------------------------------------------- #
def check_always_staffed(ctx: Context, computed: Computed) -> list[Violation]:
    return from_measure(ctx, ConstraintKind.always_staffed, C.always_staffed)


METRIC_FIELDS = [
    # (field, kind) kind: "dollars" | "hours" | "pct"
    ("total_hours", "hours"),
    ("total_wage_cost", "dollars"),
    ("overtime_hours", "hours"),
    ("premium_pay_dollars", "dollars"),
    ("coverage_pct", "pct"),
    ("gap_penalty_dollars", "dollars"),
    ("soft_penalty_dollars", "dollars"),
    ("objective_dollars", "dollars"),
    ("budget_hours_cap", "hours"),
    ("budget_hours_used", "hours"),
]


def mismatch(claimed: float, actual: float, kind: str) -> bool:
    """Off by more than 1% AND more than a small absolute floor ($1, 0.1 h, 1 point)."""
    diff = abs(claimed - actual)
    floor = {"dollars": 1.0, "hours": 0.1, "pct": 1.0}[kind]
    return diff > floor and diff > 0.01 * abs(actual)


def check_metrics_mismatch(ctx: Context, computed: Computed) -> list[Violation]:
    claimed = ctx.schedule.metrics
    if claimed is None:
        return []
    # Predictive-scheduling premiums are owed for changes to a *posted* schedule, which validate()
    # isn't given (SEMANTICS #17). Unless validate_fix has added them (premiums_exact), a claimed
    # premium above the recomputed one is accepted here and verified exactly by validate_fix.
    unverified = 0.0
    lower_bound_only = not ctx.premiums_exact and bool(law_rules(ctx.config, LawRuleType.predictive_scheduling))
    c_prem = getattr(claimed, "premium_pay_dollars", None)
    if lower_bound_only and isinstance(c_prem, (int, float)) and c_prem == c_prem:
        unverified = max(0.0, float(c_prem) - computed.metrics.premium_pay_dollars)
    out = []
    for name, kind in METRIC_FIELDS:
        c_val = getattr(claimed, name, None)
        a_val = getattr(computed.metrics, name)
        if name == "premium_pay_dollars":
            a_val += unverified
        elif name == "objective_dollars":
            a_val = round(a_val + unverified, 2)
        if not isinstance(c_val, (int, float)) or c_val != c_val:  # missing or NaN
            out.append(hard(C.metrics_mismatch, f"Claimed {name} is {c_val!r}; recomputed {a_val:g}."))
        elif mismatch(float(c_val), a_val, kind):
            out.append(hard(C.metrics_mismatch, f"Claimed {name} {c_val:g} but recomputed {a_val:g}."))
    return out


# Soft-family kinds have no ViolationCode of their own. If a leader marks one HARD we still
# enforce it, reported as code `soft` with severity `hard` so it counts as a failure.
SOFT_FAMILY = [ConstraintKind.min_hours_week, ConstraintKind.not_together,
               ConstraintKind.fair_spread, ConstraintKind.preferred_role]


def check_soft(ctx: Context, computed: Computed) -> list[Violation]:
    out = []
    for cost in computed.soft:
        f = cost.finding
        out.append(Violation(code=C.soft, severity="soft",
                             message=f"{cost.kind}: {f.message} Cost ${cost.dollars:,.2f}.",
                             employee_id=f.employee_id, role_id=f.role_id, day=f.day, start=f.start,
                             end=f.end, constraint_id=cost.constraint_id))
    for kind in SOFT_FAMILY:
        for c in hard_constraints_of(ctx, kind):
            for f in MEASURES[kind](ctx, c):
                out.append(hard(C.soft, f"{kind.value} (marked hard): {f.message}",
                                employee_id=f.employee_id, role_id=f.role_id, day=f.day,
                                start=f.start, end=f.end, constraint_id=c.id))
    return out


ALL_CHECKS = [
    check_malformed,
    check_unknown_entity,
    check_not_trained,
    check_unavailable,
    check_double_booked,
    check_shifts_per_day,
    check_outside_store_window,
    check_max_hours_week,
    check_shift_length,
    check_rest_between_shifts,
    check_days_per_week,
    check_consecutive_days,
    check_budget_hours,
    check_budget_dollars,
    check_overtime_not_allowed,
    check_meal_break,
    check_rest_break,
    check_minor_hours,
    check_minor_prohibited_role,
    check_below_minimum_wage,
    check_always_staffed,
    check_metrics_mismatch,
    check_soft,
]
