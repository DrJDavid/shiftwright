"""Everything a check needs, prepared once: lookups and the list of shifts we can reason about.

A shift is "usable" when its basic fields have sane types and values (so arithmetic on it is
safe) and its employee exists. Unusable shifts are reported by the malformed / unknown_entity
checks and skipped by every other check and by the metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shiftwright_contracts.models import Employee, Role, Schedule, Shift, StoreConfig

from .common import MINUTES_PER_DAY


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def structural_problems(shift) -> list[str]:
    """Problems that make a shift impossible to reason about. Empty list = structurally OK."""
    problems: list[str] = []
    if not isinstance(getattr(shift, "employee_id", None), str):
        problems.append("employee_id is missing or not a string")
    day = getattr(shift, "day", None)
    start = getattr(shift, "start", None)
    end = getattr(shift, "end", None)
    if not is_int(day) or not 0 <= day <= 6:
        problems.append(f"day {day!r} is not an integer 0..6")
    if not is_int(start) or not is_int(end):
        problems.append(f"start/end {start!r}..{end!r} are not integers")
    else:
        if end <= start:
            problems.append(f"end {end} is not after start {start}")
        if start < 0:
            problems.append(f"start {start} is negative")
        if end - start > MINUTES_PER_DAY:
            problems.append(f"shift is longer than 24 hours ({end - start} min)")
    breaks = getattr(shift, "breaks", None)
    segments = getattr(shift, "segments", None)
    if not isinstance(breaks, list):
        problems.append("breaks is not a list")
    else:
        for i, brk in enumerate(breaks):
            if not is_int(getattr(brk, "start", None)) or not is_int(getattr(brk, "end", None)):
                problems.append(f"break {i} has non-integer times")
            if getattr(brk, "kind", None) not in ("meal", "rest"):
                problems.append(f"break {i} kind {getattr(brk, 'kind', None)!r} is not meal/rest")
            if not isinstance(getattr(brk, "paid", None), bool):
                problems.append(f"break {i} paid flag is not a boolean")
    if not isinstance(segments, list):
        problems.append("segments is not a list")
    else:
        for i, seg in enumerate(segments):
            if not is_int(getattr(seg, "start", None)) or not is_int(getattr(seg, "end", None)):
                problems.append(f"segment {i} has non-integer times")
            if not isinstance(getattr(seg, "role_id", None), str):
                problems.append(f"segment {i} role_id is not a string")
    return problems


@dataclass
class Context:
    config: StoreConfig
    schedule: Schedule
    employees: dict[str, Employee]
    roles: dict[str, Role]
    slot: int
    structurally_ok: list[Shift] = field(default_factory=list)  # sane fields, any employee id
    usable: list[Shift] = field(default_factory=list)           # sane fields AND known employee
    # Set only by validate_fix (fix.py): law premiums the plan's changes owe (SEMANTICS #17), and
    # call-in shifts, which are not charged availability preferences (SEMANTICS #16).
    extra_premium_dollars: float = 0.0
    callin_shift_ids: set = field(default_factory=set)
    premiums_exact: bool = False  # True once validate_fix has added the predictive-scheduling premiums


def build_context(config: StoreConfig, schedule: Schedule) -> Context:
    ctx = Context(
        config=config,
        schedule=schedule,
        employees={e.id: e for e in config.employees},
        roles={r.id: r for r in config.roles},
        slot=config.store.slot_minutes,
    )
    shifts = schedule.shifts if isinstance(schedule.shifts, list) else []
    for shift in shifts:
        if structural_problems(shift):
            continue
        ctx.structurally_ok.append(shift)
        if shift.employee_id in ctx.employees:
            ctx.usable.append(shift)
    return ctx
