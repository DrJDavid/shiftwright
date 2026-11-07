"""WS2 acceptance tests: perfect schedule passes; each golden bad schedule triggers exactly its code."""
from __future__ import annotations

import pytest

from shiftwright_contracts.models import (
    AvailabilityEntry,
    AvailabilityKind,
    Break,
    BudgetApproval,
    Constraint,
    ConstraintKind,
    RoleSegment,
    RuleStatus,
    ScheduleMetrics,
    Source,
    Strength,
    ViolationCode,
)
from shiftwright_validator import recompute_metrics, validate

V = ViolationCode


def codes(report) -> set[ViolationCode]:
    return {v.code for v in report.violations}


def shift(schedule, sid):
    return next(s for s in schedule.shifts if s.id == sid)


def set_simple(s, start, end, role=None):
    """Move a single-segment shift and keep its one segment tiling it."""
    s.start, s.end = start, end
    s.segments = [RoleSegment(role_id=role or s.segments[0].role_id, start=start, end=end)]


# --------------------------------------------------------------------------- #
# The perfect schedule
# --------------------------------------------------------------------------- #
def test_perfect_schedule_passes(config, perfect):
    report = validate(config, perfect)
    assert report.violations == [], [v.message for v in report.violations]
    assert report.passed is True
    assert report.hard_count == 0


def test_perfect_schedule_metrics_match_hand_calc(config, perfect):
    m = recompute_metrics(config, perfect)
    assert m.total_hours == pytest.approx(27.5)
    assert m.total_wage_cost == pytest.approx(511.0)
    assert m.overtime_hours == 0
    assert m.premium_pay_dollars == 0
    assert m.coverage_pct == pytest.approx(100.0)
    assert m.gap_penalty_dollars == 0
    assert m.soft_penalty_dollars == 0
    assert m.objective_dollars == pytest.approx(511.0)
    assert m.budget_hours_cap == 30
    assert m.budget_hours_used == pytest.approx(27.5)


def test_gap_is_priced_not_a_violation(config, perfect):
    perfect.shifts = [s for s in perfect.shifts if s.id != "s4"]  # cashier Mon 13:00-17:00 uncovered
    report = validate(config, perfect)
    assert report.passed and report.violations == []
    m = report.recomputed_metrics
    # required 8 + 8 + 4 = 20 headcount-hours, covered 16
    assert m.coverage_pct == pytest.approx(80.0)
    assert m.gap_penalty_dollars == pytest.approx(4 * 30)
    assert m.objective_dollars == pytest.approx(511 - 56 + 120)


def test_matching_claimed_metrics_is_fine(config, perfect):
    perfect.metrics = recompute_metrics(config, perfect)
    assert validate(config, perfect).violations == []


# --------------------------------------------------------------------------- #
# Golden bad schedules: one per code, each triggers exactly that code
# --------------------------------------------------------------------------- #
def golden_malformed(config, sched):
    shift(sched, "s3").segments = [RoleSegment(role_id="cashier", start=540, end=750)]


def golden_unknown_employee(config, sched):
    shift(sched, "s3").employee_id = "ghost"


def golden_unknown_role(config, sched):
    shift(sched, "s3").segments[0].role_id = "astronaut"


def golden_not_trained(config, sched):
    shift(sched, "s3").segments[0].role_id = "stocker"  # Cam is cashier-only


def golden_unavailable(config, sched):
    config.employees[1].availability = [
        AvailabilityEntry(weekday=0, start=600, end=700, kind=AvailabilityKind.unavailable)
    ]


def golden_unavailable_on_date(config, sched):
    config.employees[1].availability = [
        AvailabilityEntry(on_date=config.store.week_start, start=0, end=1440,
                          kind=AvailabilityKind.unavailable)
    ]


def golden_double_booked(config, sched):
    set_simple(shift(sched, "s3"), 540, 840)            # Cam 09:00-14:00
    shift(sched, "s4").employee_id = "e2"               # ...and Cam 13:00-17:00


def golden_max_hours(config, sched):
    config.employees[1].max_hours_week = 3


def golden_shift_too_short(config, sched):
    set_simple(shift(sched, "s3"), 540, 660)


def golden_shift_too_long(config, sched):
    config.constraints[1].params = {"minutes": 420}  # s6 is 8h


def golden_rest(config, sched):
    shift(sched, "s4").employee_id = "e2"  # Cam 09-13 then 13-17: 0 min rest


def golden_days(config, sched):
    config.constraints[3].params = {"days": 1}
    shift(sched, "s5").employee_id = "e2"  # Cam Mon + Tue


def golden_consecutive(config, sched):
    config.constraints.append(Constraint(
        id="c_consec", kind=ConstraintKind.max_consecutive_days, params={"days": 1},
        strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed))
    shift(sched, "s5").employee_id = "e2"


def golden_budget_hours(config, sched):
    config.budget.weekly_hours_cap = 20


def golden_budget_dollars(config, sched):
    config.budget.weekly_dollar_cap = 500


def golden_overtime(config, sched):
    config.law_pack.rules[0].params = {"threshold_hours": 5, "multiplier": 1.5}


def golden_meal(config, sched):
    s6 = shift(sched, "s6")
    s6.breaks = [b for b in s6.breaks if b.kind != "meal"]
    s6.segments = [RoleSegment(role_id="stocker", start=540, end=660),
                   RoleSegment(role_id="stocker", start=690, end=1020)]


def golden_rest_break(config, sched):
    s6 = shift(sched, "s6")
    s6.breaks = [b for b in s6.breaks if b.kind != "rest"]
    s6.segments = [RoleSegment(role_id="stocker", start=540, end=780),
                   RoleSegment(role_id="stocker", start=810, end=1020)]


def golden_minor_hours(config, sched):
    config.law_pack.rules[3].params["latest_end"] = 960  # Mia works until 17:00


def golden_minor_role(config, sched):
    config.employees[4].trained_role_ids.append("pit_operator")
    shift(sched, "s4").segments[0].role_id = "pit_operator"


def golden_below_minimum_wage(config, sched):
    from shiftwright_contracts.models import LawRuleType

    # TEST-ONLY value: Mia ($14) is below a made-up $14.50 minimum
    config.law_pack.rules.append(config.law_pack.rules[0].model_copy(update=dict(
        id="TEST.minimum_wage", type=LawRuleType.minimum_wage,
        params={"dollars_per_hour": 14.5, "effective": "2026-01-01"})))


def golden_always_staffed(config, sched):
    config.constraints.append(Constraint(
        id="c_lod", kind=ConstraintKind.always_staffed,
        params={"role_id": "leader", "windows": "store_hours"},
        strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed))
    # Tuesday has no leader at all


def golden_outside_window(config, sched):
    set_simple(shift(sched, "s3"), 420, 660)  # 07:00 start, earliest allowed is 08:00


def golden_metrics_mismatch(config, sched):
    m = recompute_metrics(config, sched)
    sched.metrics = ScheduleMetrics(**{**m.model_dump(), "total_wage_cost": 999.0})


def golden_soft(config, sched):
    config.employees[1].availability = [
        AvailabilityEntry(weekday=0, start=540, end=600, kind=AvailabilityKind.preferred_off,
                          weight_dollars=5)
    ]


GOLDEN = [
    (golden_malformed, V.malformed),
    (golden_unknown_employee, V.unknown_entity),
    (golden_unknown_role, V.unknown_entity),
    (golden_not_trained, V.not_trained),
    (golden_unavailable, V.unavailable),
    (golden_unavailable_on_date, V.unavailable),
    (golden_double_booked, V.double_booked),
    (golden_max_hours, V.max_hours_week),
    (golden_shift_too_short, V.shift_length),
    (golden_shift_too_long, V.shift_length),
    (golden_rest, V.rest_between_shifts),
    (golden_days, V.days_per_week),
    (golden_consecutive, V.consecutive_days),
    (golden_budget_hours, V.budget_hours),
    (golden_budget_dollars, V.budget_dollars),
    (golden_overtime, V.overtime_not_allowed),
    (golden_meal, V.meal_break),
    (golden_rest_break, V.rest_break),
    (golden_minor_hours, V.minor_hours),
    (golden_minor_role, V.minor_prohibited_role),
    (golden_below_minimum_wage, V.below_minimum_wage),
    (golden_always_staffed, V.always_staffed),
    (golden_outside_window, V.outside_store_window),
    (golden_metrics_mismatch, V.metrics_mismatch),
    (golden_soft, V.soft),
]


@pytest.mark.parametrize("mutate,expected", GOLDEN, ids=[g[0].__name__ for g in GOLDEN])
def test_golden_bad_schedule(config, perfect, mutate, expected):
    mutate(config, perfect)
    report = validate(config, perfect)
    assert codes(report) == {expected}, [(v.code.value, v.message) for v in report.violations]
    if expected == V.soft:
        assert report.passed is True
        assert report.recomputed_metrics.soft_penalty_dollars == pytest.approx(5.0)
    else:
        assert report.passed is False
        assert report.hard_count >= 1


def test_every_code_has_a_golden():
    assert {code for _, code in GOLDEN} == set(ViolationCode)


# --------------------------------------------------------------------------- #
# Finer points
# --------------------------------------------------------------------------- #
def test_budget_approval_raises_cap(config, perfect, approved_at):
    config.budget.weekly_hours_cap = 20
    config.budget.approvals.append(BudgetApproval(
        id="a1", extra_hours=10, reason="truck", approved_by="leader", approved_at=approved_at))
    report = validate(config, perfect)
    assert report.passed
    assert report.recomputed_metrics.budget_hours_cap == 30


def test_provisional_constraints_are_ignored(config, perfect):
    config.constraints[0].params = {"minutes": 480}
    config.constraints[0].status = RuleStatus.provisional
    assert validate(config, perfect).passed


def test_overtime_cost_when_allowed(config, perfect):
    config.law_pack.rules[0].params = {"threshold_hours": 5, "multiplier": 1.5}
    config.budget.overtime_allowed = True
    report = validate(config, perfect)
    assert report.passed
    m = report.recomputed_metrics
    assert m.overtime_hours == pytest.approx(2.5)  # Pat 7.5h paid vs 5h threshold
    assert m.total_wage_cost == pytest.approx(511 + 2.5 * 18 * 0.5)


def test_minor_role_by_min_age_without_law_pack(config, perfect):
    config.law_pack = None
    config.employees[4].trained_role_ids.append("pit_operator")
    shift(perfect, "s4").segments[0].role_id = "pit_operator"
    report = validate(config, perfect)
    assert codes(report) == {V.minor_prohibited_role}


def test_rest_premium_instead_of_violation(config, perfect, kit):
    from shiftwright_contracts.models import LawRuleType

    config.law_pack.rules.append(kit.test_law(
        "TEST.rest", LawRuleType.min_rest_between_shifts,
        {"minutes": 600, "premium_multiplier": 1.5, "waivable": False}))
    config.constraints = [c for c in config.constraints if c.id != "c_rest"]
    shift(perfect, "s4").employee_id = "e2"  # Cam works 09-13 and 13-17 (wage 15)
    report = validate(config, perfect)
    assert report.passed, [v.message for v in report.violations]
    # the whole 4h second shift falls inside the 10h rest window: 4h * $15 * 0.5
    assert report.recomputed_metrics.premium_pay_dollars == pytest.approx(30.0)


def test_rest_law_without_premium_is_hard(config, perfect, kit):
    from shiftwright_contracts.models import LawRuleType

    config.law_pack.rules.append(kit.test_law(
        "TEST.rest", LawRuleType.min_rest_between_shifts,
        {"minutes": 600, "premium_multiplier": None, "waivable": False}))
    config.constraints = [c for c in config.constraints if c.id != "c_rest"]
    shift(perfect, "s4").employee_id = "e2"
    report = validate(config, perfect)
    assert codes(report) == {V.rest_between_shifts}
    assert report.violations[0].law_rule_id == "TEST.rest"


def test_overlapping_breaks_are_malformed(config, perfect):
    s6 = shift(perfect, "s6")
    s6.breaks.append(Break(start=780, end=840, kind="rest", paid=True))
    assert V.malformed in codes(validate(config, perfect))


def test_off_grid_is_malformed(config, perfect):
    set_simple(shift(perfect, "s3"), 545, 785)
    assert V.malformed in codes(validate(config, perfect))


def test_infeasible_empty_schedule_is_valid(config, perfect):
    perfect.shifts = []
    perfect.status = "infeasible"
    report = validate(config, perfect)
    assert report.passed
    assert report.recomputed_metrics.coverage_pct == 0
