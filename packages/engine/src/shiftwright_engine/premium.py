"""Predictive-scheduling (Fair Workweek) premiums for same-day changes in fix_day (SEMANTICS #17).

Amounts and exemptions come only from the law pack's `predictive_scheduling` params (WS3 keys, see
data/laws/STATUS.md "Extra param keys"). A missing param needed by the formula means: charge nothing
for that rule and say so. Changes made by fix_day are same-day, so they are always inside the notice
window and under 24 h notice (the posted schedule is assumed posted on time).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shiftwright_contracts.models import Employee, LawRuleType

from .prep import Prep

MODES = ("one_to_one", "group_offer")


@dataclass
class Premium:
    dollars: float = 0.0
    law_rule_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def note(self) -> str:
        return " ".join(self.notes)


def _rules(p: Prep, e: Employee):
    out = []
    count = p.cfg.store.employer_employee_count
    for r in p.law_of(LawRuleType.predictive_scheduling):
        pr = r.params
        over = pr.get("applies_if_employees_over")
        if over is not None and count is not None and count <= int(over):
            continue
        wmax = pr.get("covered_wage_max_hourly")
        if wmax is not None and e.wage_per_hour > float(wmax):
            continue
        out.append(r)
    return out


def _added_hours_premium(r, e: Employee, added_min: int) -> tuple[float, Optional[str]]:
    """Premium dollars for adding `added_min` minutes with < 24 h notice; (0, note) if a param is missing."""
    pr = r.params
    if pr.get("premium_basis") == "none":
        return 0.0, f"No predictability pay under {r.id} (it requires consent instead of a premium)."
    grace = pr.get("grace_minutes")
    if grace is not None and added_min < int(grace):
        return 0.0, f"No predictability pay under {r.id}: change under {int(grace)} min."
    if pr.get("premium_flat_dollars") is not None:
        return float(pr["premium_flat_dollars"]), None
    tiers = pr.get("under_24h_tiers")
    hours = None
    if tiers:
        for t in tiers:
            mx = t.get("max_changed_hours")
            if mx is None or added_min / 60 <= float(mx):
                hours = float(t["premium_hours"])
                break
    if hours is None:
        hours = pr.get("change_premium_hours_under_24h", pr.get("change_premium_hours"))
    if hours is None:
        return 0.0, f"Premium not computed: {r.id} lacks change_premium_hours."
    hours = float(hours)
    if pr.get("prorate_added_under_1h"):
        hours = min(hours, added_min / 60)
    if pr.get("change_premium_hours_max") is not None:
        hours = min(hours, float(pr["change_premium_hours_max"]))
    return round(hours * e.wage_per_hour, 2), None


def _overlap(a0: int, a1: int, spans: list[tuple[int, int]]) -> int:
    """Minutes of [a0, a1) inside the union of spans."""
    pts = sorted((max(a0, s), min(a1, t)) for s, t in spans if s < a1 and a0 < t)
    tot, cur = 0, a0
    for s, t in pts:
        s = max(s, cur)
        if t > s:
            tot += t - s
            cur = t
    return tot


def call_in_premium(p: Prep, e: Employee, start: int, end: int, added_min: int, mode: str,
                    absent_spans: list[tuple[int, int]], n_recipients: int) -> Premium:
    """A new shift [start, end) offered by text in `mode`; absent_spans = the called-out coworkers' lost
    time that day (for `exemption_only_for_absent_coworker_hours`)."""
    out = Premium()
    for r in _rules(p, e):
        pr = r.params
        out.law_rule_ids.append(r.id)
        charged = added_min
        why_exempt = None
        if pr.get("coworker_absence_exempt"):
            why_exempt = "covering an absent coworker"
        elif pr.get("voluntary_additional_hours_exempt"):
            written_ok = (not pr.get("consent_must_be_written")) or pr.get("text_message_counts_as_written") is True
            group_needed = bool(pr.get("exemption_requires_group_message"))
            min_rec = int(pr.get("exemption_min_recipients") or 2)
            if not written_ok:
                out.notes.append(f"{r.id}: a text is not written consent there, so the call-in is not exempt.")
            elif group_needed and mode != "group_offer":
                out.notes.append(f"{r.id}: only a group message to {min_rec}+ employees is exempt; "
                                 f"a one-to-one text owes predictability pay.")
            elif group_needed and n_recipients < min_rec:
                out.notes.append(f"{r.id}: a group offer needs {min_rec}+ recipients; only {n_recipients} available.")
            else:
                why_exempt = ("voluntary call-in accepted in writing" +
                              (" via a group message" if group_needed else ""))
                must = pr.get("exemption_message_must_state") or ["accepting the hours is voluntary"]
                why_exempt += "; the message must state: " + "; ".join(must)
        if why_exempt is not None:
            if pr.get("exemption_only_for_absent_coworker_hours"):
                charged = max(0, added_min - _overlap(start, end, absent_spans))
            else:
                charged = 0
        if charged <= 0:
            out.notes.append(f"No predictability pay: {why_exempt}, exempt under {r.id}.")
            continue
        dollars, note = _added_hours_premium(r, e, charged)
        if note:
            out.notes.append(note)
        elif dollars > 0:
            part = "" if charged == added_min else f" for the {charged / 60:g} h not covering an absent coworker"
            out.notes.append(f"{r.id}: +${dollars:,.2f} predictability pay (hours added with under 24 h notice{part}).")
        out.dollars += dollars
    out.dollars = round(out.dollars, 2)
    return out


def extension_premium(p: Prep, e: Employee, added_min: int) -> Premium:
    """An extension decided by the leader (no written consent): always premium-bearing."""
    out = Premium()
    for r in _rules(p, e):
        out.law_rule_ids.append(r.id)
        dollars, note = _added_hours_premium(r, e, added_min)
        if note:
            out.notes.append(note)
        elif dollars > 0:
            out.notes.append(f"{r.id}: +${dollars:,.2f} predictability pay (shift extended with under 24 h notice).")
        out.dollars += dollars
    out.dollars = round(out.dollars, 2)
    return out
