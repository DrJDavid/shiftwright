"""Soft costs: confirmed soft constraints and availability preferences, priced in dollars."""
from __future__ import annotations

from dataclasses import dataclass

from shiftwright_contracts.models import AvailabilityKind, RuleStatus, Strength

from .common import day_name, fmt_time, overlap_minutes, shift_interval, week_minute
from .context import Context
from .measure import MEASURES, Finding


@dataclass
class SoftCost:
    kind: str  # ConstraintKind value or "availability_preference"
    finding: Finding
    dollars: float
    constraint_id: str | None = None


def availability_windows(ctx: Context, employee) -> list[tuple[object, int, int]]:
    """(entry, week_start_minute, week_end_minute) for each availability entry that falls in this week."""
    windows = []
    for entry in employee.availability:
        if entry.weekday is not None:
            day = entry.weekday
        elif entry.on_date is not None:
            day = (entry.on_date - ctx.config.store.week_start).days
            if not 0 <= day <= 6:
                continue
        else:
            continue
        windows.append((entry, week_minute(day, entry.start), week_minute(day, entry.end)))
    return windows


def availability_costs(ctx: Context) -> list[SoftCost]:
    costs = []
    for employee in ctx.config.employees:
        shifts = [s for s in ctx.usable if s.employee_id == employee.id and s.id not in ctx.callin_shift_ids]
        for entry, w_start, w_end in availability_windows(ctx, employee):
            if entry.weight_dollars <= 0:
                continue
            day = w_start // 1440
            label = f"{day_name(day)} {fmt_time(entry.start)}-{fmt_time(entry.end)}"
            scheduled = sum(overlap_minutes(*shift_interval(s), w_start, w_end) for s in shifts)
            if entry.kind == AvailabilityKind.preferred_off and scheduled > 0:
                hours = scheduled / 60
                costs.append(SoftCost("availability_preference", Finding(
                    hours, f"Scheduled {scheduled} min in preferred-off window {label}.",
                    employee.id, None, day, entry.start, entry.end), hours * entry.weight_dollars))
            if entry.kind == AvailabilityKind.preferred_on:
                missing = max(0, (w_end - w_start) - scheduled)
                if missing > 0:
                    hours = missing / 60
                    costs.append(SoftCost("availability_preference", Finding(
                        hours, f"Not scheduled for {missing} min of preferred-on window {label}.",
                        employee.id, None, day, entry.start, entry.end),
                        hours * entry.weight_dollars))
    return costs


def soft_costs(ctx: Context) -> list[SoftCost]:
    costs = []
    for c in ctx.config.constraints:
        if c.status != RuleStatus.confirmed or c.strength != Strength.soft:
            continue
        measure = MEASURES.get(c.kind)
        if measure is None:
            continue
        for finding in measure(ctx, c):
            costs.append(SoftCost(c.kind.value, finding, finding.amount * c.weight_dollars, c.id))
    costs.extend(availability_costs(ctx))
    return costs
