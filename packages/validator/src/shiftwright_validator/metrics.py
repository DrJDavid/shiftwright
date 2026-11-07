"""Recompute a schedule's true metrics from scratch.

Definitions used (see STATUS.md and contracts/requests/ws2-validator-semantics.md):
  * Paid hours of a shift = clock span minus UNPAID breaks (paid breaks count as hours and cost).
  * total_hours = budget_hours_used = sum of paid hours.
  * total_wage_cost = paid hours x wage + overtime premium (the extra part above straight time).
  * overtime_hours: from the law pack's daily_overtime / weekly_overtime rules only. Daily overtime
    hours are taken out before the weekly threshold is applied, so no hour is counted twice.
    A shift's hours count on the day the shift starts. No OT rule in the pack => no overtime.
  * premium_pay_dollars: law premiums. Today only min_rest_between_shifts with a
    premium_multiplier (hours of the later shift that fall inside the rest window x wage x
    (multiplier - 1)). Predictive-scheduling and reporting-time pay need data validate() isn't given.
  * coverage_pct is 0..100: covered headcount-hours / required headcount-hours. A slot is covered
    by a segment only if the segment spans the whole slot. Extra people don't over-cover other slots.
    No demand at all => 100.
  * gap_penalty_dollars = sum over slots of missing headcount x slot hours x role.gap_penalty_per_hour.
  * objective = total_wage_cost + premium_pay + gap_penalty + soft_penalty.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shiftwright_contracts.models import LawRuleType, Schedule, ScheduleMetrics, StoreConfig

from .common import as_float, as_int, law_rules, paid_minutes, shift_interval, shifts_by_employee, week_minute
from .context import Context, build_context
from .soft import SoftCost, soft_costs


@dataclass
class EmployeeOvertime:
    overtime_hours: float = 0.0
    premium_dollars: float = 0.0


@dataclass
class Computed:
    """Everything recompute produces, kept around so checks can reuse it."""
    metrics: ScheduleMetrics
    paid_hours_by_employee: dict[str, float] = field(default_factory=dict)
    paid_hours_by_employee_day: dict[tuple[str, int], float] = field(default_factory=dict)
    overtime_by_employee: dict[str, EmployeeOvertime] = field(default_factory=dict)
    soft: list[SoftCost] = field(default_factory=list)


def _strictest_ot_rule(config: StoreConfig, rule_type: LawRuleType):
    """Lowest threshold wins; ties go to the higher multiplier."""
    best = None
    for rule in law_rules(config, rule_type):
        threshold = as_float(rule.params.get("threshold_hours"))
        if threshold is None:
            continue
        multiplier = as_float(rule.params.get("multiplier"), 1.5)
        double = as_float(rule.params.get("double_threshold_hours"))
        candidate = (threshold, -multiplier, multiplier, double)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    threshold, _, multiplier, double = best
    return threshold, multiplier, double


def overtime_for(config: StoreConfig, wage: float, total_hours: float,
                 hours_by_day: dict[int, float]) -> EmployeeOvertime:
    result = EmployeeOvertime()
    daily = _strictest_ot_rule(config, LawRuleType.daily_overtime)
    weekly = _strictest_ot_rule(config, LawRuleType.weekly_overtime)
    daily_ot_hours = 0.0
    if daily is not None:
        threshold, multiplier, double = daily
        for hours in hours_by_day.values():
            if double is not None and double > threshold:
                band = max(0.0, min(hours, double) - threshold)
                double_band = max(0.0, hours - double)
            else:
                band = max(0.0, hours - threshold)
                double_band = 0.0
            daily_ot_hours += band + double_band
            result.premium_dollars += band * wage * (multiplier - 1) + double_band * wage * 1.0
    weekly_ot_hours = 0.0
    if weekly is not None:
        threshold, multiplier, _ = weekly
        weekly_ot_hours = max(0.0, (total_hours - daily_ot_hours) - threshold)
        result.premium_dollars += weekly_ot_hours * wage * (multiplier - 1)
    result.overtime_hours = daily_ot_hours + weekly_ot_hours
    return result


def rest_premium_rule(config: StoreConfig):
    """The min_rest law rule that carries a premium (longest rest window wins), or None."""
    best = None
    for rule in law_rules(config, LawRuleType.min_rest_between_shifts):
        multiplier = as_float(rule.params.get("premium_multiplier"))
        minutes = as_int(rule.params.get("minutes"), 0)
        if multiplier is None or minutes <= 0:
            continue
        if best is None or minutes > best[0]:
            best = (minutes, multiplier, rule)
    return best


def rest_premium_dollars(ctx: Context) -> float:
    found = rest_premium_rule(ctx.config)
    if found is None:
        return 0.0
    minutes, multiplier, _ = found
    total = 0.0
    for employee_id, shifts in shifts_by_employee(ctx.usable).items():
        wage = ctx.employees[employee_id].wage_per_hour
        for prev, nxt in zip(shifts, shifts[1:]):
            prev_end = shift_interval(prev)[1]
            n_start, n_end = shift_interval(nxt)
            if n_start < prev_end:
                continue  # overlapping: double-booked, not a rest question
            inside = max(0, min(n_end, prev_end + minutes) - n_start)
            total += inside / 60 * wage * (multiplier - 1)
    return total


def coverage(ctx: Context) -> tuple[float, float, float]:
    """(required headcount-hours, covered headcount-hours, gap penalty dollars)."""
    slot = ctx.slot
    required: dict[tuple[str, int], int] = {}
    for d in ctx.config.demand:
        t = d.start
        while t < d.end:
            key = (d.role_id, week_minute(d.day, t))
            required[key] = required.get(key, 0) + d.headcount
            t += slot
    staffed: dict[tuple[str, int], int] = {}
    for shift in ctx.usable:
        for seg in shift.segments:
            start = max(seg.start, shift.start)
            end = min(seg.end, shift.end)
            t = start + (-start) % slot
            while t + slot <= end:
                key = (seg.role_id, week_minute(shift.day, t))
                staffed[key] = staffed.get(key, 0) + 1
                t += slot
    slot_hours = slot / 60
    req_hours = cov_hours = gap_dollars = 0.0
    for key, need in required.items():
        have = min(need, staffed.get(key, 0))
        req_hours += need * slot_hours
        cov_hours += have * slot_hours
        role = ctx.roles.get(key[0])
        penalty = role.gap_penalty_per_hour if role else 0.0
        gap_dollars += (need - have) * slot_hours * penalty
    return req_hours, cov_hours, gap_dollars


def compute(ctx: Context) -> Computed:
    config = ctx.config
    by_emp: dict[str, float] = {}
    by_emp_day: dict[tuple[str, int], float] = {}
    for shift in ctx.usable:
        hours = paid_minutes(shift) / 60
        by_emp[shift.employee_id] = by_emp.get(shift.employee_id, 0.0) + hours
        key = (shift.employee_id, shift.day)
        by_emp_day[key] = by_emp_day.get(key, 0.0) + hours

    total_hours = 0.0
    base_wages = 0.0
    ot_hours = 0.0
    ot_premium = 0.0
    overtime: dict[str, EmployeeOvertime] = {}
    for employee_id, hours in by_emp.items():
        wage = ctx.employees[employee_id].wage_per_hour
        total_hours += hours
        base_wages += hours * wage
        days = {day: h for (eid, day), h in by_emp_day.items() if eid == employee_id}
        ot = overtime_for(config, wage, hours, days)
        overtime[employee_id] = ot
        ot_hours += ot.overtime_hours
        ot_premium += ot.premium_dollars

    premium = rest_premium_dollars(ctx)
    req_hours, cov_hours, gap_dollars = coverage(ctx)
    soft = soft_costs(ctx)
    soft_dollars = sum(c.dollars for c in soft)
    wage_cost = base_wages + ot_premium
    cap = config.budget.weekly_hours_cap + sum(a.extra_hours for a in config.budget.approvals)

    metrics = ScheduleMetrics(
        total_hours=round(total_hours, 2),
        total_wage_cost=round(wage_cost, 2),
        overtime_hours=round(ot_hours, 2),
        premium_pay_dollars=round(premium, 2),
        coverage_pct=round(100.0 * cov_hours / req_hours, 2) if req_hours > 0 else 100.0,
        gap_penalty_dollars=round(gap_dollars, 2),
        soft_penalty_dollars=round(soft_dollars, 2),
        objective_dollars=round(wage_cost + premium + gap_dollars + soft_dollars, 2),
        budget_hours_cap=round(cap, 2),
        budget_hours_used=round(total_hours, 2),
    )
    return Computed(metrics, by_emp, by_emp_day, overtime, soft)


def recompute_metrics(config: StoreConfig, schedule: Schedule) -> ScheduleMetrics:
    return compute(build_context(config, schedule)).metrics
