"""Measure how far a schedule breaks one constraint.

Each function takes the prepared Context and one Constraint and returns a list of Findings.
A Finding's `amount` is in the unit used to price the soft version of the constraint:

  min/max_shift_length     hours short / over, per shift
  min_rest_between_shifts  hours of rest missing, per pair of shifts
  max_days_per_week        extra days, per employee
  max_consecutive_days     extra days in the longest run, per employee
  always_staffed           uncovered hours, per contiguous window
  min_hours_week           hours short, per employee
  not_together             overlapping hours, per pair of shifts
  fair_spread              excess occurrences, per employee
  preferred_role           hours worked in another role, per employee

Hard constraints turn findings into hard violations (checks.py); soft ones into dollars (soft.py).
"""
from __future__ import annotations

from dataclasses import dataclass

from shiftwright_contracts.models import Constraint, ConstraintKind

from .common import (
    applies_to,
    as_int,
    day_name,
    fmt_time,
    overlap_minutes,
    paid_minutes,
    shift_interval,
    shifts_by_employee,
    span_minutes,
    week_minute,
)
from .context import Context


@dataclass
class Finding:
    amount: float
    message: str
    employee_id: str | None = None
    role_id: str | None = None
    day: int | None = None
    start: int | None = None
    end: int | None = None


def shift_length(ctx: Context, c: Constraint) -> list[Finding]:
    minutes = as_int(c.params.get("minutes"), -1)
    if minutes < 0:
        return []
    findings = []
    for shift in ctx.usable:
        if not applies_to(c, shift.employee_id):
            continue
        length = span_minutes(shift)
        if c.kind == ConstraintKind.min_shift_length and length < minutes:
            findings.append(Finding(
                (minutes - length) / 60,
                f"Shift {shift.id} is {length} min; minimum is {minutes} min.",
                shift.employee_id, None, shift.day, shift.start, shift.end))
        if c.kind == ConstraintKind.max_shift_length and length > minutes:
            findings.append(Finding(
                (length - minutes) / 60,
                f"Shift {shift.id} is {length} min; maximum is {minutes} min.",
                shift.employee_id, None, shift.day, shift.start, shift.end))
    return findings


def rest_shortfalls(ctx: Context, minutes: int, employee_filter=None) -> list[Finding]:
    """Pairs of back-to-back shifts (same employee) with less than `minutes` rest between them.
    Overlapping shifts are double-booking, not a rest problem, so they are skipped here."""
    findings = []
    for employee_id, shifts in shifts_by_employee(ctx.usable).items():
        if employee_filter is not None and not employee_filter(employee_id):
            continue
        for prev, nxt in zip(shifts, shifts[1:]):
            prev_end = shift_interval(prev)[1]
            next_start = shift_interval(nxt)[0]
            rest = next_start - prev_end
            if 0 <= rest < minutes:
                findings.append(Finding(
                    (minutes - rest) / 60,
                    f"Only {rest} min rest between shift {prev.id} and shift {nxt.id}; "
                    f"needs {minutes} min.",
                    employee_id, None, nxt.day, nxt.start, nxt.end))
    return findings


def min_rest(ctx: Context, c: Constraint) -> list[Finding]:
    minutes = as_int(c.params.get("minutes"), 0)
    if minutes <= 0:
        return []
    return rest_shortfalls(ctx, minutes, lambda eid: applies_to(c, eid))


def days_worked(ctx: Context) -> dict[str, set[int]]:
    """Days each employee works (a shift counts on the day it starts)."""
    days: dict[str, set[int]] = {}
    for shift in ctx.usable:
        days.setdefault(shift.employee_id, set()).add(shift.day)
    return days


def max_days(ctx: Context, c: Constraint) -> list[Finding]:
    limit = as_int(c.params.get("days"), -1)
    if limit < 0:
        return []
    findings = []
    for employee_id, days in days_worked(ctx).items():
        if applies_to(c, employee_id) and len(days) > limit:
            findings.append(Finding(
                len(days) - limit,
                f"Works {len(days)} days; maximum is {limit}.", employee_id))
    return findings


def max_consecutive(ctx: Context, c: Constraint) -> list[Finding]:
    limit = as_int(c.params.get("days"), -1)
    if limit < 0:
        return []
    findings = []
    for employee_id, days in days_worked(ctx).items():
        if not applies_to(c, employee_id):
            continue
        longest = run = 0
        for day in range(7):
            run = run + 1 if day in days else 0
            longest = max(longest, run)
        if longest > limit:
            findings.append(Finding(
                longest - limit,
                f"Works {longest} consecutive days; maximum is {limit}.", employee_id))
    return findings


def role_covered_intervals(ctx: Context, role_id: str) -> list[tuple[int, int]]:
    """Merged week-minute intervals where at least one usable segment of `role_id` is worked."""
    raw = []
    for shift in ctx.usable:
        for seg in shift.segments:
            if seg.role_id != role_id:
                continue
            start = max(seg.start, shift.start)
            end = min(seg.end, shift.end)
            if end > start:
                raw.append((week_minute(shift.day, start), week_minute(shift.day, end)))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(raw):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def always_staffed(ctx: Context, c: Constraint) -> list[Finding]:
    """Uncovered stretches of each window, to the minute (a 10-min break is a 10-min gap)."""
    role_id = c.params.get("role_id")
    if not isinstance(role_id, str):
        return []
    use_staff_hours = c.params.get("windows") == "staff_hours"
    store = ctx.config.store
    covered = role_covered_intervals(ctx, role_id)
    findings = []
    for hours in store.hours:
        lo, hi = hours.open, hours.close
        if use_staff_hours:
            lo, hi = lo - store.pre_open_minutes, hi + store.post_close_minutes
        base = week_minute(hours.day, 0)
        t = lo
        for c_start, c_end in covered:
            c_start, c_end = c_start - base, c_end - base
            if c_end <= t or c_start >= hi:
                continue
            if c_start > t:
                findings.append(_staffing_gap(role_id, hours.day, t, c_start))
            t = max(t, c_end)
            if t >= hi:
                break
        if t < hi:
            findings.append(_staffing_gap(role_id, hours.day, t, hi))
    return findings


def _staffing_gap(role_id: str, day: int, start: int, end: int) -> Finding:
    return Finding(
        (end - start) / 60,
        f"No {role_id} on duty {day_name(day)} {fmt_time(start)}-{fmt_time(end)}.",
        None, role_id, day, start, end)


def min_hours_week(ctx: Context, c: Constraint) -> list[Finding]:
    paid: dict[str, int] = {}
    for shift in ctx.usable:
        paid[shift.employee_id] = paid.get(shift.employee_id, 0) + paid_minutes(shift)
    findings = []
    for employee in ctx.config.employees:
        if not applies_to(c, employee.id) or employee.min_hours_week <= 0:
            continue
        hours = paid.get(employee.id, 0) / 60
        if hours < employee.min_hours_week:
            findings.append(Finding(
                employee.min_hours_week - hours,
                f"Scheduled {hours:g} h; wants at least {employee.min_hours_week:g} h.",
                employee.id))
    return findings


def not_together(ctx: Context, c: Constraint) -> list[Finding]:
    ids = c.params.get("employee_ids")
    if not isinstance(ids, list) or len(ids) != 2:
        return []
    a, b = ids
    findings = []
    for sa in ctx.usable:
        if sa.employee_id != a:
            continue
        for sb in ctx.usable:
            if sb.employee_id != b:
                continue
            minutes = overlap_minutes(*shift_interval(sa), *shift_interval(sb))
            if minutes > 0:
                findings.append(Finding(
                    minutes / 60,
                    f"{a} and {b} overlap for {minutes} min (shifts {sa.id}, {sb.id}).",
                    a, None, sa.day, sa.start, sa.end))
    return findings


def shift_class(ctx: Context, shift, which: str) -> bool:
    """open = starts before store open; close = ends after store close; weekend = Sat/Sun."""
    if which == "weekend":
        return shift.day in (5, 6)
    hours = next((h for h in ctx.config.store.hours if h.day == shift.day), None)
    if hours is None:
        return False
    if which == "open":
        return shift.start < hours.open
    if which == "close":
        return shift.end > hours.close
    return False


def fair_spread(ctx: Context, c: Constraint) -> list[Finding]:
    which = c.params.get("shift_class")
    limit = as_int(c.params.get("max_per_employee"), -1)
    if which not in ("open", "close", "weekend") or limit < 0:
        return []
    counts: dict[str, int] = {}
    for shift in ctx.usable:
        if applies_to(c, shift.employee_id) and shift_class(ctx, shift, which):
            counts[shift.employee_id] = counts.get(shift.employee_id, 0) + 1
    findings = []
    for employee_id, count in counts.items():
        if count > limit:
            findings.append(Finding(
                count - limit, f"Has {count} {which} shifts; fair share is {limit}.", employee_id))
    return findings


def preferred_role(ctx: Context, c: Constraint) -> list[Finding]:
    employee_id = c.params.get("employee_id")
    role_id = c.params.get("role_id")
    minutes = 0
    for shift in ctx.usable:
        if shift.employee_id != employee_id:
            continue
        for seg in shift.segments:
            if seg.role_id != role_id:
                minutes += max(0, seg.end - seg.start)
    if minutes == 0:
        return []
    return [Finding(minutes / 60, f"Works {minutes} min outside preferred role {role_id}.",
                    employee_id, role_id)]


MEASURES = {
    ConstraintKind.min_shift_length: shift_length,
    ConstraintKind.max_shift_length: shift_length,
    ConstraintKind.min_rest_between_shifts: min_rest,
    ConstraintKind.max_days_per_week: max_days,
    ConstraintKind.max_consecutive_days: max_consecutive,
    ConstraintKind.always_staffed: always_staffed,
    ConstraintKind.min_hours_week: min_hours_week,
    ConstraintKind.not_together: not_together,
    ConstraintKind.fair_spread: fair_spread,
    ConstraintKind.preferred_role: preferred_role,
    # week_stability needs the previous week's schedule, which validate() is not given.
}
