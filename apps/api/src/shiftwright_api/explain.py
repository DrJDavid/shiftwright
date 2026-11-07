"""Deterministic phrasing of engine gap reasons. Adds no facts: every clause maps to one GapReason."""
from __future__ import annotations

from shiftwright_contracts.models import Gap, GapReason, GapReasonCode, StoreConfig

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_PHRASE = {
    GapReasonCode.not_trained: "is not trained for it",
    GapReasonCode.unavailable: "is unavailable then",
    GapReasonCode.at_max_hours: "is at max hours",
    GapReasonCode.budget_cap: "would push the week over the hours budget",
    GapReasonCode.law_rule: "is blocked by a labor-law rule",
    GapReasonCode.minor_rule: "is blocked by a minor-labor rule",
    GapReasonCode.rest_rule: "would break a rest-between-shifts rule",
    GapReasonCode.already_assigned: "is working a higher-priority role then",
    GapReasonCode.cheaper_to_leave_gap: "would cost more than leaving the gap",
}


def hhmm(minute: int) -> str:
    m = minute % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def phrase_gap(config: StoreConfig, gap: Gap, reasons: list[GapReason]) -> str:
    roles = {r.id: r.name for r in config.roles}
    names = {e.id: e.name for e in config.employees}
    head = (f"{roles.get(gap.role_id, gap.role_id)} {DAYS[gap.day]} {hhmm(gap.start)}–{hhmm(gap.end)} "
            f"uncovered ({gap.missing_headcount} short, ${gap.penalty_dollars:,.2f})")
    if not reasons:
        return head + ". The engine gave no per-person reasons."
    parts = []
    for r in reasons:
        clause = f"{names.get(r.employee_id, r.employee_id)} {_PHRASE.get(r.code, r.code.value)}"
        if r.law_rule_id:
            clause += f" ({r.law_rule_id})"
        elif r.constraint_id:
            clause += f" (rule {r.constraint_id})"
        parts.append(clause)
    return head + ": " + "; ".join(parts) + "."
