"""validate_fix(request, plan): check a call-out repair plan (SEMANTICS #16, #17).

Checks, all against the posted schedule `request.schedule`:
  1. Shape: the plan's outreach_mode matches the request's (when the request sets one); every
     extend/reassign action shows up in schedule_if_none_accept.
  2. Nothing before `now` on `request.day` (and nothing on any other day) changed, except the
     called-out employees' own shifts, which are removed. Every employee whose repair-day hours
     change is named by an action (or, in schedule_if_all_accept, is an outreach candidate).
  3. Called-out employees don't work after they called out; declined employees aren't re-asked.
  4. Both schedules pass validate(); their metrics include the predictive-scheduling premiums
     recomputed here, and call-in shifts are not charged availability preferences (#16).
  5. Predictive-scheduling premiums are recomputed from law-pack params alone and compared to
     FixAction.premium_pay_dollars (summed per employee) and OutreachCandidate.premium_pay_dollars.
     A difference over 2 cents is a `metrics_mismatch`.

Premium formula (law params only; keys from data/laws/STATUS.md "Extra param keys"):
  * A rule applies if its `applies_to` matches Store.sector (#19, via law_rules), unless
    `premium_basis == "none"`
    (NYC: prohibitions, not premiums), Store.employer_employee_count <= applies_if_employees_over,
    or the employee's wage > covered_wage_max_hourly. Thresholds we have no data for
    (min_covered_employees, min_local_employees, min_locations, city scopes) are assumed met.
  * Per affected employee on the repair day, compare minutes worked (shift spans) before and after.
    The called-out employees are never charged. Only added -> "added"; only removed -> "reduced";
    both -> "moved" if no hours are lost, else "reduced" on the net loss. Changes shorter than
    `grace_minutes` are free. Notice = shift start - now (0 if the shift already started); the change
    is priced only within `change_premium_window_days` (else `notice_days`) of the shift.
  * added: hours = change_premium_hours (change_premium_hours_under_24h when notice < 24 h);
    with `prorate_added_under_1h` min(hours, added hours); capped by change_premium_hours_max.
    moved: moved_premium_hours. reduced: if reduced_fraction_notice_hours is null or notice < it,
    reduced_hours_fraction x (hours lost, or the shift's scheduled hours when
    reduced_hours_measure == "scheduled_shift"), capped by reduced_premium_hours_cap; otherwise
    reduced_premium_hours. With notice < 24 h, `under_24h_tiers` (first tier whose max_changed_hours
    >= changed hours, null = no limit) replaces the hours. Dollars = hours x wage, or
    premium_flat_dollars when set. A missing param => $0 for that rule (never a guess).
  * Exempt added minutes: with `coworker_absence_exempt`, minutes covering a called-out coworker's
    hours (any lever). Otherwise only call-ins: needs voluntary_additional_hours_exempt; if
    consent_must_be_written, text_message_counts_as_written must be true; if
    exemption_requires_group_message, the plan's mode must be group_offer with at least
    exemption_min_recipients (default 2) in the queue; with exemption_only_for_absent_coworker_hours
    only the minutes covering called-out coworkers' hours are exempt. Remaining added minutes are
    priced as an "added" change.
  * Several rules: the most expensive one counts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shiftwright_contracts.models import (
    FixPlan,
    FixRequest,
    LawRuleType,
    Lever,
    Schedule,
    Shift,
    ValidationReport,
    Violation,
    ViolationCode,
)

from .common import MINUTES_PER_DAY, as_float, as_int, fmt_time, law_rules
from .context import build_context
from .validate import validate, validate_context

C = ViolationCode
CENTS_TOLERANCE = 0.02


def cents(x: float) -> float:
    """Round half up to cents (8.625 -> 8.63), avoiding float artefacts."""
    return int(x * 100 + 0.5 + 1e-9) / 100 if x >= 0 else -cents(-x)


def hard(code, message, **kw) -> Violation:
    return Violation(code=code, severity="hard", message=message, **kw)


# --------------------------------------------------------------------------- #
# Minutes worked
# --------------------------------------------------------------------------- #
def day_minutes(shifts: list[Shift], employee_id: str, day: int) -> set[int]:
    """Minutes of `day` (0..1440+) inside the employee's shifts that start on that day."""
    out: set[int] = set()
    for s in shifts:
        if s.employee_id == employee_id and s.day == day and s.end > s.start:
            out |= set(range(max(0, s.start), min(s.end, 2 * MINUTES_PER_DAY)))
    return out


def callout_absent_minutes(request: FixRequest) -> set[int]:
    """Minutes the called-out employees were scheduled for, from when they called out."""
    out: set[int] = set()
    for co in request.callouts:
        if co.day == request.day:
            out |= {m for m in day_minutes(request.schedule.shifts, co.employee_id, co.day)
                    if m >= co.reported_at}
    return out


@dataclass
class Change:
    employee_id: str
    added: set[int]
    removed: set[int]
    scheduled_minutes: int   # length of the posted shift(s) that day
    shift_start: int         # earliest minute of the shift, before or after


def diff(employee_id: str, before: set[int], after: set[int]) -> Change | None:
    added, removed = after - before, before - after
    if not added and not removed:
        return None
    return Change(employee_id, added, removed, len(before), min(before | after))


# --------------------------------------------------------------------------- #
# Premiums
# --------------------------------------------------------------------------- #
@dataclass
class Premium:
    dollars: float = 0.0
    rule_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def rule_applies(config, rule) -> bool:
    """Sector (#19) is already filtered by law_rules(); here: NYC-style prohibitions and size."""
    p = rule.params
    if p.get("premium_basis") == "none":
        return False
    threshold = p.get("applies_if_employees_over")
    count = config.store.employer_employee_count
    if threshold is not None and count is not None and count <= as_float(threshold, 0):
        return False
    return True


def _tier_hours(p: dict, changed_hours: float):
    for tier in p.get("under_24h_tiers") or []:
        top = tier.get("max_changed_hours")
        if top is None or changed_hours <= as_float(top, 0):
            return as_float(tier.get("premium_hours"))
    return None


def premium_hours(p: dict, kind: str, change_minutes: int, scheduled_minutes: int, notice: int):
    """Premium hours for one change under one rule's params, or (None, missing-param) if a needed
    param is absent."""
    under_24h = notice < MINUTES_PER_DAY
    changed_hours = change_minutes / 60
    if under_24h and p.get("under_24h_tiers"):
        hours = _tier_hours(p, changed_hours)
        return (hours, None) if hours is not None else (None, "under_24h_tiers")
    if kind == "added":
        key = "change_premium_hours_under_24h" if under_24h and p.get(
            "change_premium_hours_under_24h") is not None else "change_premium_hours"
        hours = as_float(p.get(key))
        if hours is None:
            return None, key
        if p.get("prorate_added_under_1h"):
            hours = min(hours, changed_hours)
        cap = as_float(p.get("change_premium_hours_max"))
        return (min(hours, cap) if cap is not None else hours), None
    if kind == "moved":
        hours = as_float(p.get("moved_premium_hours"))
        return (hours, None) if hours is not None else (None, "moved_premium_hours")
    # reduced
    frac_notice = as_float(p.get("reduced_fraction_notice_hours"))
    if frac_notice is None or notice / 60 < frac_notice:
        fraction = as_float(p.get("reduced_hours_fraction"))
        if fraction is None:
            return None, "reduced_hours_fraction"
        basis = scheduled_minutes if p.get("reduced_hours_measure") == "scheduled_shift" else change_minutes
        hours = fraction * basis / 60
        cap = as_float(p.get("reduced_premium_hours_cap"))
        return (min(hours, cap) if cap is not None else hours), None
    hours = as_float(p.get("reduced_premium_hours"))
    return (hours, None) if hours is not None else (None, "reduced_premium_hours")


def exempt_added(p: dict, added: set[int], absent: set[int], via_call_in: bool,
                 mode: str, queue_len: int) -> set[int]:
    """Which added minutes are exempt from the premium."""
    exempt = added & absent if p.get("coworker_absence_exempt") else set()
    if not via_call_in or not p.get("voluntary_additional_hours_exempt"):
        return exempt
    if p.get("consent_must_be_written") and not p.get("text_message_counts_as_written"):
        return exempt
    if p.get("exemption_requires_group_message"):
        if mode != "group_offer" or queue_len < as_int(p.get("exemption_min_recipients"), 2):
            return exempt
    if p.get("exemption_only_for_absent_coworker_hours"):
        return exempt | (added & absent)
    return set(added)


def price_change(request: FixRequest, change: Change, via_call_in: bool, mode: str,
                 queue_len: int) -> Premium:
    config = request.config
    employee = next((e for e in config.employees if e.id == change.employee_id), None)
    result = Premium()
    if employee is None:
        return result
    absent = callout_absent_minutes(request)
    notice = max(0, change.shift_start - request.now)
    best = None
    for rule in law_rules(config, LawRuleType.predictive_scheduling):
        p = rule.params
        if not rule_applies(config, rule):
            continue
        wage_cap = as_float(p.get("covered_wage_max_hourly"))
        if wage_cap is not None and employee.wage_per_hour > wage_cap:
            continue
        window_days = as_float(p.get("change_premium_window_days")) or as_float(p.get("notice_days"), 0)
        if notice >= window_days * MINUTES_PER_DAY:
            continue
        grace = as_int(p.get("grace_minutes"), 0)
        added, removed = set(change.added), set(change.removed)
        if added and not removed:
            added -= exempt_added(p, added, absent, via_call_in, mode, queue_len)
        if not added and not removed:
            dollars, note = 0.0, f"exempt under {rule.id}"
        else:
            if added and removed:
                kind = "moved" if len(added) >= len(removed) else "reduced"
                minutes = max(len(added), len(removed)) if kind == "moved" else len(removed) - len(added)
            elif added:
                kind, minutes = "added", len(added)
            else:
                kind, minutes = "reduced", len(removed)
            if minutes < grace:
                dollars, note = 0.0, f"{rule.id}: change under {grace} min grace"
            else:
                hours, missing = premium_hours(p, kind, minutes, change.scheduled_minutes, notice)
                if hours is None:
                    dollars, note = 0.0, f"premium not computed: {rule.id} lacks {missing}"
                elif p.get("premium_flat_dollars") is not None:
                    dollars, note = as_float(p.get("premium_flat_dollars"), 0.0), f"{rule.id}: flat"
                else:
                    dollars = hours * employee.wage_per_hour
                    note = f"{rule.id}: {kind} {minutes} min, {hours:g} h x ${employee.wage_per_hour:g}"
        if best is None or dollars > best[0]:
            best = (dollars, rule.id, note)
    if best is not None:
        result.dollars = cents(best[0])
        result.rule_ids = [best[1]]
        result.notes = [best[2]]
    return result


def employees_on_day(*schedules: Schedule, day: int) -> list[str]:
    ids: set[str] = set()
    for sched in schedules:
        ids |= {s.employee_id for s in sched.shifts if s.day == day and isinstance(s.employee_id, str)}
    return sorted(ids)


def schedule_premiums(request: FixRequest, plan: FixPlan, after: Schedule,
                      callin_ids: set[str]) -> dict[str, Premium]:
    """Premium per employee for the changes between the posted schedule and `after`."""
    called_out = {co.employee_id for co in request.callouts}
    out = {}
    for eid in employees_on_day(request.schedule, after, day=request.day):
        if eid in called_out:
            continue
        change = diff(eid, day_minutes(request.schedule.shifts, eid, request.day),
                      day_minutes(after.shifts, eid, request.day))
        if change is not None:
            out[eid] = price_change(request, change, eid in callin_ids, plan.outreach_mode,
                                    len(plan.outreach_queue))
    return out


def candidate_premium(request: FixRequest, plan: FixPlan, candidate) -> Premium:
    """Extra premium the candidate's proposed shift adds on top of the immediate actions."""
    eid = candidate.employee_id
    base_shifts = [s for s in plan.schedule_if_none_accept.shifts if s.employee_id == eid]
    with_callin = [s for s in base_shifts if s.id != candidate.proposed_shift.id] + [candidate.proposed_shift]
    posted = day_minutes(request.schedule.shifts, eid, request.day)
    before_change = diff(eid, posted, day_minutes(base_shifts, eid, request.day))
    after_change = diff(eid, posted, day_minutes(with_callin, eid, request.day))
    n = len(plan.outreach_queue)
    base = price_change(request, before_change, False, plan.outreach_mode, n) if before_change else Premium()
    total = price_change(request, after_change, True, plan.outreach_mode, n) if after_change else Premium()
    return Premium(cents(total.dollars - base.dollars), total.rule_ids, total.notes)


# --------------------------------------------------------------------------- #
# Structural checks
# --------------------------------------------------------------------------- #
def _timeline(shifts: list[Shift], employee_id: str, cutoff: int | None, days=None) -> list[tuple]:
    """What an employee does, as comparable tuples, before week-minute `cutoff` (or on `days`)."""
    out = []
    for s in shifts:
        if s.employee_id != employee_id:
            continue
        if days is not None and s.day not in days:
            continue
        base = s.day * MINUTES_PER_DAY
        items = [("shift", s.start, s.end, "")] + [("seg", g.start, g.end, g.role_id) for g in s.segments] \
            + [("break", b.start, b.end, b.kind) for b in s.breaks]
        for kind, start, end, label in items:
            start, end = base + start, base + end
            if cutoff is not None:
                if start >= cutoff:
                    continue
                end = min(end, cutoff)
            out.append((kind, start, end, label))
    return sorted(out)


def unchanged_checks(request: FixRequest, label: str, after: Schedule) -> list[Violation]:
    out = []
    called_out = {co.employee_id for co in request.callouts}
    cutoff = request.day * MINUTES_PER_DAY + request.now
    other_days = [d for d in range(7) if d != request.day]
    ids = {s.employee_id for s in request.schedule.shifts} | {s.employee_id for s in after.shifts}
    for eid in sorted(i for i in ids if isinstance(i, str)):
        if eid in called_out:
            continue
        if _timeline(request.schedule.shifts, eid, cutoff) != _timeline(after.shifts, eid, cutoff):
            out.append(hard(C.malformed, f"[{label}] {eid}'s schedule before now "
                                         f"(day {request.day} {fmt_time(request.now)}) was changed.",
                            employee_id=eid, day=request.day))
        elif _timeline(request.schedule.shifts, eid, None, other_days) != \
                _timeline(after.shifts, eid, None, other_days):
            out.append(hard(C.malformed, f"[{label}] {eid}'s shifts on another day than the repair "
                                         f"day {request.day} were changed.", employee_id=eid))
    for co in request.callouts:
        start = co.day * MINUTES_PER_DAY + co.reported_at
        end = (co.day + 1) * MINUTES_PER_DAY
        for s in after.shifts:
            if s.employee_id == co.employee_id and \
                    max(start, s.day * MINUTES_PER_DAY + s.start) < min(end, s.day * MINUTES_PER_DAY + s.end):
                out.append(hard(C.unavailable, f"[{label}] {co.employee_id} called out at "
                                               f"{fmt_time(co.reported_at)} but still works "
                                               f"{fmt_time(s.start)}-{fmt_time(s.end)}.",
                                employee_id=co.employee_id, day=s.day, start=s.start, end=s.end))
    return out


def unexplained_changes(request: FixRequest, plan: FixPlan, label: str, after: Schedule) -> list[Violation]:
    """Every employee whose repair-day hours change must be named by an action (or, in
    schedule_if_all_accept, be an outreach candidate); otherwise nobody is told and nothing is priced."""
    called_out = {co.employee_id for co in request.callouts}
    named = {a.employee_id for a in plan.actions if a.employee_id}
    if label == "schedule_if_all_accept":
        named |= {c.employee_id for c in plan.outreach_queue}
    out = []
    for eid in employees_on_day(request.schedule, after, day=request.day):
        if eid in called_out or eid in named:
            continue
        change = diff(eid, day_minutes(request.schedule.shifts, eid, request.day),
                      day_minutes(after.shifts, eid, request.day))
        if change is not None:
            out.append(hard(C.malformed, f"[{label}] {eid}'s hours change on day {request.day} "
                                         f"(+{len(change.added)} / -{len(change.removed)} min) but no "
                                         f"action or outreach candidate names them.",
                            employee_id=eid, day=request.day))
    return out


def plan_shape_checks(request: FixRequest, plan: FixPlan) -> list[Violation]:
    out = []
    if request.outreach_mode is not None and plan.outreach_mode != request.outreach_mode:
        out.append(hard(C.malformed, f"Request asked for outreach_mode {request.outreach_mode!r}; "
                                     f"plan priced {plan.outreach_mode!r}."))
    declined = set(request.declined_employee_ids)
    called_out = {co.employee_id for co in request.callouts}
    for cand in plan.outreach_queue:
        if cand.employee_id in declined | called_out:
            why = "already declined" if cand.employee_id in declined else "called out"
            out.append(hard(C.unavailable, f"Outreach candidate {cand.employee_id} {why} today.",
                            employee_id=cand.employee_id))
    none_shifts = plan.schedule_if_none_accept.shifts
    for a in plan.actions:
        if a.lever not in (Lever.extend, Lever.reassign) or a.employee_id is None:
            continue
        # The action's span must be worked (extend spans can mix roles), and its role must be
        # worked somewhere inside that span.
        worked: set[int] = set()
        in_role = False
        for s in none_shifts:
            if s.employee_id == a.employee_id and s.day == request.day:
                worked |= set(range(s.start, s.end))
                in_role |= any(g.role_id == a.role_id and g.start < a.end and a.start < g.end
                               for g in s.segments)
        if not set(range(a.start, a.end)) <= worked or not in_role:
            out.append(hard(C.malformed, f"Action {a.lever.value} {a.employee_id} {a.role_id} "
                                         f"{fmt_time(a.start)}-{fmt_time(a.end)} is not in "
                                         f"schedule_if_none_accept.", employee_id=a.employee_id,
                            role_id=a.role_id, day=request.day, start=a.start, end=a.end))
    return out


def premium_checks(request: FixRequest, plan: FixPlan) -> list[Violation]:
    out = []
    immediate = schedule_premiums(request, plan, plan.schedule_if_none_accept, set())
    claimed: dict[str, float] = {}
    for a in plan.actions:
        if a.employee_id is not None:
            claimed[a.employee_id] = claimed.get(a.employee_id, 0.0) + a.premium_pay_dollars
    for eid in sorted(set(claimed) | set(immediate)):
        mine = immediate.get(eid, Premium())
        if abs(claimed.get(eid, 0.0) - mine.dollars) > CENTS_TOLERANCE:
            out.append(hard(C.metrics_mismatch,
                            f"Predictive-scheduling premium for {eid}'s immediate changes: plan says "
                            f"${claimed.get(eid, 0.0):,.2f}, recomputed ${mine.dollars:,.2f} "
                            f"({'; '.join(mine.notes) or 'no rule applies'}).",
                            employee_id=eid, law_rule_id=(mine.rule_ids or [None])[0]))
    for cand in plan.outreach_queue:
        mine = candidate_premium(request, plan, cand)
        if abs(cand.premium_pay_dollars - mine.dollars) > CENTS_TOLERANCE:
            out.append(hard(C.metrics_mismatch,
                            f"Predictive-scheduling premium for call-in #{cand.rank} {cand.employee_id} "
                            f"({plan.outreach_mode}): plan says ${cand.premium_pay_dollars:,.2f}, "
                            f"recomputed ${mine.dollars:,.2f} "
                            f"({'; '.join(mine.notes) or 'no rule applies'}).",
                            employee_id=cand.employee_id, law_rule_id=(mine.rule_ids or [None])[0]))
    return out


def callin_shift_ids(plan: FixPlan, schedule: Schedule) -> set:
    proposed = {(c.employee_id, c.proposed_shift.day, c.proposed_shift.start, c.proposed_shift.end)
                for c in plan.outreach_queue}
    ids = {c.proposed_shift.id for c in plan.outreach_queue}
    return {s.id for s in schedule.shifts if s.id in ids or (s.employee_id, s.day, s.start, s.end) in proposed}


def validate_plan_schedule(request: FixRequest, plan: FixPlan, label: str, schedule: Schedule):
    callin_ids = callin_shift_ids(plan, schedule)
    callin_employees = {s.employee_id for s in schedule.shifts if s.id in callin_ids}
    premiums = schedule_premiums(request, plan, schedule, callin_employees)
    ctx = build_context(request.config, schedule)
    ctx.extra_premium_dollars = sum(p.dollars for p in premiums.values())
    ctx.callin_shift_ids = callin_ids
    ctx.premiums_exact = True
    report = validate_context(ctx)
    for v in report.violations:
        v.message = f"[{label}] {v.message}"
    return report


def validate_fix(request: FixRequest, plan: FixPlan) -> ValidationReport:
    """One report for the whole plan. recomputed_metrics are schedule_if_all_accept's.
    Never raises: an unexpected error becomes one hard `malformed` violation."""
    try:
        return _validate_fix(request, plan)
    except Exception as exc:  # noqa: BLE001
        report = validate(request.config, plan.schedule_if_all_accept)
        crash = hard(C.malformed, f"Validator could not evaluate the fix plan: {type(exc).__name__}: {exc}")
        return ValidationReport(passed=False, hard_count=report.hard_count + 1,
                                violations=[crash, *report.violations],
                                recomputed_metrics=report.recomputed_metrics)


def _validate_fix(request: FixRequest, plan: FixPlan) -> ValidationReport:
    violations = plan_shape_checks(request, plan)
    reports = {}
    for label in ("schedule_if_all_accept", "schedule_if_none_accept"):
        schedule = getattr(plan, label)
        reports[label] = validate_plan_schedule(request, plan, label, schedule)
        violations += reports[label].violations
        violations += unchanged_checks(request, label, schedule)
        violations += unexplained_changes(request, plan, label, schedule)
    violations += premium_checks(request, plan)
    hard_count = sum(1 for v in violations if v.severity == "hard")
    return ValidationReport(passed=hard_count == 0, hard_count=hard_count, violations=violations,
                            recomputed_metrics=reports["schedule_if_all_accept"].recomputed_metrics)
