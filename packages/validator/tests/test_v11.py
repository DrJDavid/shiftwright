"""Contracts v1.1 (contracts/SEMANTICS.md): 5-minute breaks, per-minute coverage, school_week,
below_minimum_wage. Law values here are TEST-ONLY (see conftest)."""
from __future__ import annotations

import pytest

from shiftwright_contracts.models import (
    Break,
    Constraint,
    ConstraintKind,
    LawRuleType,
    RoleSegment,
    RuleStatus,
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


# --------------------------------------------------------------------------- #
# Breaks on the 5-minute grid
# --------------------------------------------------------------------------- #
def ten_minute_rest_breaks(sched, first=(660, 670), second=(905, 915)):
    """Pat's 09:00-17:00: two 10-min paid rest breaks + the 13:00-13:30 meal."""
    s6 = shift(sched, "s6")
    s6.breaks = [Break(start=first[0], end=first[1], kind="rest", paid=True),
                 Break(start=780, end=810, kind="meal", paid=False),
                 Break(start=second[0], end=second[1], kind="rest", paid=True)]
    s6.segments = [RoleSegment(role_id="stocker", start=540, end=first[0]),
                   RoleSegment(role_id="stocker", start=first[1], end=780),
                   RoleSegment(role_id="stocker", start=810, end=second[0]),
                   RoleSegment(role_id="stocker", start=second[1], end=1020)]


def test_ten_minute_rest_breaks_on_five_minute_grid_pass(config, perfect):
    ten_minute_rest_breaks(perfect)  # 11:00-11:10 and 15:05-15:15
    report = validate(config, perfect)
    assert report.violations == [], [v.message for v in report.violations]
    assert report.recomputed_metrics.total_hours == pytest.approx(27.5)


def test_break_on_seven_minute_boundary_is_malformed(config, perfect):
    ten_minute_rest_breaks(perfect, first=(667, 677))
    report = validate(config, perfect)
    assert codes(report) == {V.malformed}, [v.message for v in report.violations]
    assert any("break grid" in v.message for v in report.violations)


def test_segment_edge_off_slot_grid_away_from_a_break_is_malformed(config, perfect):
    s3 = shift(perfect, "s3")  # Cam 09:00-13:00, no breaks
    s3.segments = [RoleSegment(role_id="cashier", start=540, end=605),
                   RoleSegment(role_id="cashier", start=605, end=780)]
    assert codes(validate(config, perfect)) == {V.malformed}


def test_shift_times_stay_on_slot_grid(config, perfect):
    s3 = shift(perfect, "s3")
    s3.start = 545
    s3.segments = [RoleSegment(role_id="cashier", start=545, end=780)]
    assert V.malformed in codes(validate(config, perfect))


def test_ca_rest_break_rule_accepts_exactly_ten_minutes(config, perfect, kit):
    # CA-shaped rest rule (TEST-ONLY values): 10 min per 4 h; the 4 h test shifts are exempt
    config.law_pack.rules[2] = kit.test_law(
        "TEST.rest_break_ca", LawRuleType.rest_break,
        {"per_minutes_worked": 240, "duration": 10, "paid": True, "not_required_under_minutes": 250})
    ten_minute_rest_breaks(perfect)  # Pat's 8 h shift needs 2, has exactly 2 x 10 min
    report = validate(config, perfect)
    assert report.violations == [], [v.message for v in report.violations]
    # a 5-minute second break is too short
    ten_minute_rest_breaks(perfect, second=(905, 910))
    report = validate(config, perfect)
    assert codes(report) == {V.rest_break}, [v.message for v in report.violations]
    assert report.violations[0].law_rule_id == "TEST.rest_break_ca"


# --------------------------------------------------------------------------- #
# Per-minute coverage
# --------------------------------------------------------------------------- #
def give_leader_a_ten_minute_break(sched):
    s1 = shift(sched, "s1")  # Lee, leader Mon 09:00-13:00
    s1.breaks = [Break(start=600, end=610, kind="rest", paid=True)]
    s1.segments = [RoleSegment(role_id="leader", start=540, end=600),
                   RoleSegment(role_id="leader", start=610, end=780)]


def test_coverage_is_per_minute(config, perfect):
    give_leader_a_ten_minute_break(perfect)
    m = recompute_metrics(config, perfect)
    # required 1200 headcount-minutes (8 h + 8 h + 4 h); the 10-min break leaves 10 uncovered
    assert m.coverage_pct == pytest.approx(round(100 * 1190 / 1200, 2))
    assert m.gap_penalty_dollars == pytest.approx(round(10 / 60 * 50, 2))  # leader $50/h
    assert m.total_hours == pytest.approx(27.5)  # paid break still counts


def test_slot_aligned_coverage_unchanged(config, perfect):
    perfect.shifts = [s for s in perfect.shifts if s.id != "s4"]
    m = recompute_metrics(config, perfect)
    assert m.coverage_pct == pytest.approx(80.0)
    assert m.gap_penalty_dollars == pytest.approx(120.0)


def test_always_staffed_gap_is_measured_to_the_minute(config, perfect):
    give_leader_a_ten_minute_break(perfect)
    config.constraints.append(Constraint(
        id="c_lod", kind=ConstraintKind.always_staffed,
        params={"role_id": "leader", "windows": "store_hours"},
        strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed))
    gaps = [(v.day, v.start, v.end) for v in validate(config, perfect).violations
            if v.code == V.always_staffed]
    assert (0, 600, 610) in gaps
    assert (1, 540, 1020) in gaps  # Tuesday has no leader at all
    assert len(gaps) == 2


# --------------------------------------------------------------------------- #
# Store.school_week
# --------------------------------------------------------------------------- #
def two_minor_rules(config, kit):
    """School-week rule: max 3 h/day (Mia works 4 h Mon). Non-school rule: no start before 14:00
    (Mia starts 13:00). TEST-ONLY values."""
    config.law_pack.rules[3].params["max_hours_day"] = 3
    config.law_pack.rules.append(kit.test_law(
        "TEST.minor_limits_summer", LawRuleType.minor_limits,
        {"age_min": 14, "age_max": 17, "school_week": False, "max_hours_day": 8,
         "max_hours_week": 40, "earliest_start": 840, "latest_end": None, "latest_end_summer": None}))


def minor_rule_ids(report) -> set[str]:
    return {v.law_rule_id for v in report.violations if v.code == V.minor_hours}


@pytest.mark.parametrize("school_week,expected", [
    (None, {"TEST.minor_limits", "TEST.minor_limits_summer"}),
    (True, {"TEST.minor_limits"}),
    (False, {"TEST.minor_limits_summer"}),
])
def test_school_week_selects_minor_rules(config, perfect, kit, school_week, expected):
    two_minor_rules(config, kit)
    config.store.school_week = school_week
    report = validate(config, perfect)
    assert codes(report) == {V.minor_hours}
    assert minor_rule_ids(report) == expected


def test_non_school_week_has_no_school_days(config, perfect, kit):
    # WS3 key: on a non-school day the cap is max_hours_non_school_day. With school_week=False the
    # non-school rule's plain max_hours_day applies on every day.
    config.law_pack.rules[3].params["school_week"] = False
    config.law_pack.rules[3].params["max_hours_day"] = 3
    config.store.school_week = False
    assert minor_rule_ids(validate(config, perfect)) == {"TEST.minor_limits"}
    config.store.school_week = True
    assert validate(config, perfect).violations == []


# --------------------------------------------------------------------------- #
# below_minimum_wage
# --------------------------------------------------------------------------- #
def add_min_wage(config, kit, dollars, effective, rule_id="TEST.minimum_wage"):
    config.law_pack.rules.append(kit.test_law(
        rule_id, LawRuleType.minimum_wage, {"dollars_per_hour": dollars, "effective": effective}))


def test_below_minimum_wage_one_per_scheduled_employee(config, perfect, kit):
    add_min_wage(config, kit, 15.5, "2026-01-01")  # Cam $15 and Mia $14 are below
    report = validate(config, perfect)
    hits = [v for v in report.violations if v.code == V.below_minimum_wage]
    assert codes(report) == {V.below_minimum_wage}
    assert sorted(v.employee_id for v in hits) == ["e2", "e5"]
    assert all(v.law_rule_id == "TEST.minimum_wage" and v.severity == "hard" for v in hits)


def test_unscheduled_employee_below_minimum_is_ignored(config, perfect, kit):
    add_min_wage(config, kit, 14.5, "2026-01-01")
    perfect.shifts = [s for s in perfect.shifts if s.employee_id != "e5"]
    assert V.below_minimum_wage not in codes(validate(config, perfect))


def test_minimum_wage_in_effect_on_week_start(config, perfect, kit):
    add_min_wage(config, kit, 14.0, "2026-01-01", "TEST.mw.old")
    add_min_wage(config, kit, 20.0, "2027-01-01", "TEST.mw.future")  # not yet in effect
    assert V.below_minimum_wage not in codes(validate(config, perfect))
    add_min_wage(config, kit, 14.5, "2026-11-09", "TEST.mw.new")     # effective on week_start
    hits = [v for v in validate(config, perfect).violations if v.code == V.below_minimum_wage]
    assert [(v.employee_id, v.law_rule_id) for v in hits] == [("e5", "TEST.mw.new")]
