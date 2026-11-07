"""Contracts v1.5 (SEMANTICS #15, #19-#23): split shifts, tipped pay, role tags, age_min, sector.
Law values are TEST-ONLY (see conftest)."""
from __future__ import annotations

import pytest

from shiftwright_contracts.models import (
    ConstraintKind,
    LawRuleType,
    RoleSegment,
    Sector,
    ViolationCode,
)
from shiftwright_validator import recompute_metrics, validate

V = ViolationCode


def codes(report) -> set:
    return {v.code for v in report.violations}


def shift(schedule, sid):
    return next(s for s in schedule.shifts if s.id == sid)


def add_rule(config, kit, rule_id, rule_type, params):
    config.law_pack.rules.append(kit.test_law(rule_id, rule_type, params))


# --------------------------------------------------------------------------- #
# Split shifts (#23)
# --------------------------------------------------------------------------- #
def test_split_shift_allowed_when_store_allows_two(config, perfect):
    config.store.max_shifts_per_day = 2
    shift(perfect, "s4").employee_id = "e2"  # Cam 09-13 and 13-17; store min_rest (600) spans days only
    report = validate(config, perfect)
    assert report.violations == [], [v.message for v in report.violations]


def test_three_shifts_exceed_two(config, perfect, kit):
    config.store.max_shifts_per_day = 2
    config.constraints = [c for c in config.constraints if c.kind != ConstraintKind.min_shift_length]
    s3 = shift(perfect, "s3")
    s3.end = 660
    s3.segments = [RoleSegment(role_id="cashier", start=540, end=660)]
    perfect.shifts.append(kit.simple_shift("s3b", "e2", 0, 660, 780, "cashier"))
    shift(perfect, "s4").employee_id = "e2"
    assert codes(validate(config, perfect)) == {V.shifts_per_day}


def test_each_split_is_measured_alone(config, perfect, kit):
    """Shift length is per shift: two 2 h pieces break the 4 h minimum even though the day is 4 h."""
    config.store.max_shifts_per_day = 2
    s3 = shift(perfect, "s3")
    s3.end = 660
    s3.segments = [RoleSegment(role_id="cashier", start=540, end=660)]
    perfect.shifts.append(kit.simple_shift("s3b", "e2", 0, 660, 780, "cashier"))
    report = validate(config, perfect)
    assert codes(report) == {V.shift_length}
    assert len([v for v in report.violations if v.code == V.shift_length]) == 2


def test_minor_daily_cap_sums_split_shifts(config, perfect, kit):
    config.store.max_shifts_per_day = 2
    config.law_pack.rules[3].params["max_hours_day"] = 6
    perfect.shifts.append(kit.simple_shift("s4b", "e5", 0, 540, 780, "cashier"))  # Mia 09-13 + 13-17
    perfect.shifts = [s for s in perfect.shifts if s.id != "s3"]
    report = validate(config, perfect)
    assert codes(report) == {V.minor_hours}, [v.message for v in report.violations]


@pytest.mark.parametrize("excludes,expected", [(None, {V.rest_between_shifts}), (True, set())])
def test_law_rest_spans_split_unless_excluded(config, perfect, kit, excludes, expected):
    config.store.max_shifts_per_day = 2
    params = {"minutes": 600, "premium_multiplier": None, "waivable": False}
    if excludes is not None:
        params["excludes_same_day_split"] = excludes
    add_rule(config, kit, "TEST.rest", LawRuleType.min_rest_between_shifts, params)
    shift(perfect, "s4").employee_id = "e2"
    assert codes(validate(config, perfect)) == expected


# --------------------------------------------------------------------------- #
# Tipped pay (#20) and tipped minimum (#15)
# --------------------------------------------------------------------------- #
def tip_cashiers(config, cash=5.0):
    next(r for r in config.roles if r.id == "cashier").tipped = True
    config.employees[1].tipped_wage_per_hour = cash  # Cam (wage $15)


def test_tipped_shift_pays_cash_wage(config, perfect):
    tip_cashiers(config)
    m = recompute_metrics(config, perfect)
    assert m.total_wage_cost == pytest.approx(511 - 4 * 15 + 4 * 5)  # Cam's 4 h at $5


def test_mixed_role_shift_pays_full_wage(config, perfect):
    tip_cashiers(config)
    config.employees[2].tipped_wage_per_hour = 4.0  # Sam, Tue 09-13 cashier -> half cashier, half stocker
    s5 = shift(perfect, "s5")
    s5.segments = [RoleSegment(role_id="cashier", start=540, end=660),
                   RoleSegment(role_id="stocker", start=660, end=780)]
    m = recompute_metrics(config, perfect)
    assert m.total_wage_cost == pytest.approx(511 - 4 * 15 + 4 * 5)  # Sam still at $16


def test_overtime_premium_on_full_wage(config, perfect):
    next(r for r in config.roles if r.id == "stocker").tipped = True
    config.employees[3].tipped_wage_per_hour = 5.0  # Pat, stocker 7.5 paid h, wage $18
    config.law_pack.rules[0].params = {"threshold_hours": 5, "multiplier": 1.5}
    config.budget.overtime_allowed = True
    m = recompute_metrics(config, perfect)
    assert m.total_wage_cost == pytest.approx(511 - 7.5 * 18 + 7.5 * 5 + 2.5 * 18 * 0.5)


def test_tipped_without_tip_credit_rule_uses_full_minimum(config, perfect, kit):
    tip_cashiers(config, cash=5.0)
    add_rule(config, kit, "TEST.mw", LawRuleType.minimum_wage, {"dollars_per_hour": 10, "effective": "2026-01-01"})
    report = validate(config, perfect)
    hits = [v for v in report.violations if v.code == V.below_minimum_wage]
    assert [(v.employee_id, v.law_rule_id) for v in hits] == [("e2", "TEST.mw")]
    assert "no tip credit" in hits[0].message


def test_tipped_wage_not_checked_without_tipped_shift(config, perfect, kit):
    config.employees[1].tipped_wage_per_hour = 1.0  # cashier isn't a tipped role
    add_rule(config, kit, "TEST.tmw", LawRuleType.tipped_minimum_wage,
             {"cash_wage_per_hour": 3.0, "max_tip_credit_per_hour": None, "effective": "2026-01-01"})
    assert validate(config, perfect).violations == []


# --------------------------------------------------------------------------- #
# Role tags and age_min (#21)
# --------------------------------------------------------------------------- #
def test_known_tags_are_fine(config, perfect):
    config.role_tags["cashier"] = ["fryer", "alcohol_service"]
    assert validate(config, perfect).violations == []


def test_age_min_lower_bound(config, perfect, kit):
    config.role_tags["cashier"] = ["fryer"]
    add_rule(config, kit, "TEST.fryer", LawRuleType.minor_prohibited_roles,
             {"age_below": 16, "age_min": 14, "role_tags": ["fryer"]})
    config.employees[4].age = 16  # Mia: not below 16
    assert V.minor_prohibited_role not in codes(validate(config, perfect))
    config.employees[4].age = 15
    assert V.minor_prohibited_role in codes(validate(config, perfect))


def test_age_min_excludes_younger(config, perfect, kit):
    """A rule for 16-17 doesn't cover a 15-year-old (another rule would)."""
    config.role_tags["cashier"] = ["alcohol_service"]
    add_rule(config, kit, "TEST.alcohol", LawRuleType.minor_prohibited_roles,
             {"age_below": 18, "age_min": 16, "role_tags": ["alcohol_service"]})
    config.employees[4].age = 15
    assert V.minor_prohibited_role not in codes(validate(config, perfect))


# --------------------------------------------------------------------------- #
# Sector (#19)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sector,applies_to,applies", [
    (None, "food", True),            # unknown sector: protective default
    (Sector.other, "food", True),
    (Sector.retail, "food", False),
    (Sector.food, "food", True),
    (Sector.retail, "both", True),
    (Sector.hospitality, "retail", False),
    (Sector.hospitality, ["food", "hospitality"], True),
])
def test_sector_applicability(config, perfect, kit, sector, applies_to, applies):
    config.store.sector = sector
    add_rule(config, kit, "TEST.mw", LawRuleType.minimum_wage,
             {"dollars_per_hour": 14.5, "effective": "2026-01-01", "applies_to": applies_to})
    assert (V.below_minimum_wage in codes(validate(config, perfect))) is applies


def test_rule_without_applies_to_applies_everywhere(config, perfect, kit):
    config.store.sector = Sector.hospitality
    add_rule(config, kit, "TEST.mw", LawRuleType.minimum_wage, {"dollars_per_hour": 14.5, "effective": "2026-01-01"})
    assert V.below_minimum_wage in codes(validate(config, perfect))
