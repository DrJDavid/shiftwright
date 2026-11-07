"""One check function per ViolationCode. Each takes the Context (+ recomputed numbers) and
returns a list of Violations. Plain loops; clarity over speed."""
from __future__ import annotations

from shiftwright_contracts.models import (
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
            if brk.start % slot or brk.end % slot:
                bad(f"{brk.kind} break {fmt_time(brk.start)}-{fmt_time(brk.end)} is off the grid.")
            minutes = set(range(max(brk.start, shift.start), min(brk.end, shift.end)))
            if minutes & break_minutes:
                bad("breaks overlap each other.")
            break_minutes |= minutes

        # segments must tile [start, end) minus breaks exactly, without overlaps
        covered: set[int] = set()
        tiling_ok = True
        for seg in shift.segments:
            if seg.end <= seg.start:
                bad(f"segment {seg.role_id} {fmt_time(seg.start)}-{fmt_time(seg.end)} has no length.")
                tiling_ok = False
                continue
            if seg.start % slot or seg.end % slot:
                bad(f"segment {seg.role_id} {fmt_time(seg.start)}-{fmt_time(seg.end)} is off the grid.")
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
        for f in rest_shortfalls(ctx, minutes):
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
def check_minor_hours(ctx: Context, computed: Computed) -> list[Violation]:
    """Applies every minor_limits rule matching the employee's age (school-week and not), i.e. the
    most protective reading, because the config doesn't say whether this is a school week."""
    out = []
    for rule in law_rules(ctx.config, LawRuleType.minor_limits):
        p = rule.params
        age_min, age_max = as_int(p.get("age_min"), 0), as_int(p.get("age_max"), -1)
        max_day = as_float(p.get("max_hours_day"))
        max_week = as_float(p.get("max_hours_week"))
        earliest = p.get("earliest_start")
        latest = p.get("latest_end")
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
            if max_day is not None:
                for (e, day), hours in sorted(computed.paid_hours_by_employee_day.items()):
                    if e == eid and hours > max_day + EPS:
                        flag(f"{hours:g} h on {day_name(day)}; limit {max_day:g} h.", day=day)
            for shift in ctx.usable:
                if shift.employee_id != eid:
                    continue
                if earliest is not None and shift.start < as_int(earliest):
                    flag(f"starts {fmt_time(shift.start)}, earliest allowed {fmt_time(as_int(earliest))}.",
                         day=shift.day, start=shift.start, end=shift.end)
                if latest is not None and shift.end > as_int(latest):
                    flag(f"works until {fmt_time(shift.end)}, latest allowed {fmt_time(as_int(latest))}.",
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
                if employee.age < as_int(rule.params.get("age_below"), 0) and tags & set(banned):
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
    out = []
    for name, kind in METRIC_FIELDS:
        c_val = getattr(claimed, name, None)
        a_val = getattr(computed.metrics, name)
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
    check_always_staffed,
    check_metrics_mismatch,
    check_soft,
]
