"""Small shared helpers for the validator. Plain functions, no cleverness.

Time model (from contracts/models.py):
  * A shift's start/end, and its breaks' and segments' start/end, are minutes after local
    midnight of the shift's `day`. end may exceed 1440 for overnight shifts.
  * To compare things across days we use "week minutes": day * 1440 + minute.
  * Intervals are half-open [start, end).
"""
from __future__ import annotations

from datetime import timedelta

from shiftwright_contracts.models import (
    Constraint,
    ConstraintKind,
    Employee,
    LawRule,
    LawRuleType,
    RuleStatus,
    Shift,
    Strength,
    StoreConfig,
)

MINUTES_PER_DAY = 1440


def week_minute(day: int, minute: int) -> int:
    return day * MINUTES_PER_DAY + minute


def shift_interval(shift: Shift) -> tuple[int, int]:
    """The shift as a half-open interval in week minutes."""
    return week_minute(shift.day, shift.start), week_minute(shift.day, shift.end)


def overlap_minutes(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def span_minutes(shift: Shift) -> int:
    """Clock length of the shift, breaks included. Never negative."""
    return max(0, shift.end - shift.start)


def unpaid_break_minutes(shift: Shift) -> int:
    total = 0
    for brk in shift.breaks:
        if not brk.paid:
            # only count the part of the break that is inside the shift
            total += overlap_minutes(brk.start, brk.end, shift.start, shift.end)
    return total


def paid_minutes(shift: Shift) -> int:
    """Paid time = clock span minus unpaid breaks. Paid breaks count as hours and cost."""
    return max(0, span_minutes(shift) - unpaid_break_minutes(shift))


def employees_by_id(config: StoreConfig) -> dict[str, Employee]:
    return {e.id: e for e in config.employees}


def roles_by_id(config: StoreConfig) -> dict:
    return {r.id: r for r in config.roles}


def applies_to_sector(rule: LawRule, sector) -> bool:
    """SEMANTICS #19: `applies_to` "both" or the store's sector; unknown/other sector => applies;
    no `applies_to` => applies. A list of sectors is accepted too."""
    wanted = rule.params.get("applies_to") if isinstance(rule.params, dict) else None
    if wanted is None or wanted == "both":
        return True
    sector_value = getattr(sector, "value", sector)
    if sector_value is None or sector_value == "other":
        return True
    values = wanted if isinstance(wanted, list) else [wanted]
    return sector_value in values or "both" in values


def law_rules(config: StoreConfig, rule_type: LawRuleType) -> list[LawRule]:
    """Rules of one type that apply to this store's sector."""
    if config.law_pack is None:
        return []
    return [r for r in config.law_pack.rules
            if r.type == rule_type and applies_to_sector(r, config.store.sector)]


def is_tipped_shift(shift: Shift, employee: Employee, roles: dict) -> bool:
    """SEMANTICS #20: every segment in a tipped role, and the employee has a tipped cash wage."""
    if employee.tipped_wage_per_hour is None or not shift.segments:
        return False
    return all(getattr(roles.get(seg.role_id), "tipped", False) for seg in shift.segments)


def shift_wage(shift: Shift, employee: Employee, roles: dict) -> float:
    """Hourly pay for this shift's paid hours (#20)."""
    if is_tipped_shift(shift, employee, roles):
        return employee.tipped_wage_per_hour
    return employee.wage_per_hour


def active_constraints(config: StoreConfig, kind: ConstraintKind) -> list[Constraint]:
    """Only confirmed constraints count. Provisional and rejected ones are ignored."""
    return [c for c in config.constraints if c.kind == kind and c.status == RuleStatus.confirmed]


def hard_constraints(config: StoreConfig, kind: ConstraintKind) -> list[Constraint]:
    return [c for c in active_constraints(config, kind) if c.strength == Strength.hard]


def soft_constraints(config: StoreConfig, kind: ConstraintKind) -> list[Constraint]:
    return [c for c in active_constraints(config, kind) if c.strength == Strength.soft]


def applies_to(constraint: Constraint, employee_id: str) -> bool:
    ids = constraint.applies_to_employee_ids
    return ids is None or employee_id in ids


def shifts_by_employee(shifts: list[Shift]) -> dict[str, list[Shift]]:
    """Group shifts per employee, each list sorted by start in week minutes."""
    grouped: dict[str, list[Shift]] = {}
    for shift in shifts:
        grouped.setdefault(shift.employee_id, []).append(shift)
    for employee_shifts in grouped.values():
        employee_shifts.sort(key=lambda s: shift_interval(s))
    return grouped


def as_int(value, default: int = 0) -> int:
    """Read a numeric law/constraint param defensively."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def date_of_day(config: StoreConfig, day: int):
    return config.store.week_start + timedelta(days=day)


def fmt_time(minute: int) -> str:
    """510 -> '08:30', 1830 -> '30:30' (next day)."""
    sign = "-" if minute < 0 else ""
    minute = abs(minute)
    return f"{sign}{minute // 60:02d}:{minute % 60:02d}"


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day_name(day: int) -> str:
    if 0 <= day <= 6:
        return DAY_NAMES[day]
    return f"day{day}"
