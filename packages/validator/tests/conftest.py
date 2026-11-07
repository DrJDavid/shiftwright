"""Hand-built test store and a hand-checked perfect schedule.

Everything here is TEST DATA. The law pack values below are made up for testing the
validator's mechanics; they are NOT real labor law and must never be shown as such.
(Real law comes only from data/laws.)
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from shiftwright_contracts.models import (
    Break,
    Budget,
    Citation,
    Constraint,
    ConstraintKind,
    DayHours,
    DemandRequirement,
    DemandSource,
    Department,
    Employee,
    EmploymentStatus,
    Jurisdiction,
    LawPack,
    LawRule,
    LawRuleType,
    Role,
    RoleSegment,
    RuleStatus,
    Schedule,
    Shift,
    Source,
    Store,
    StoreConfig,
    Strength,
)

WEEK_START = date(2026, 11, 9)  # a Monday

TEST_CITATION = Citation(
    url="https://example.test/TEST-ONLY",
    title="TEST-ONLY made-up rule for validator unit tests (not law)",
    excerpt="Test fixture value. Not a real law.",
    last_verified=date(2026, 11, 6),
)
JUR = Jurisdiction(state="TX")


def test_law(rule_id: str, rule_type: LawRuleType, params: dict) -> LawRule:
    return LawRule(
        id=rule_id,
        jurisdiction=JUR,
        level="state",
        type=rule_type,
        params=params,
        summary="TEST-ONLY rule",
        citation=TEST_CITATION,
        confidence="low",
    )


def build_law_pack() -> LawPack:
    return LawPack(
        jurisdiction=JUR,
        coverage="full",
        rules=[
            test_law("TEST.weekly_overtime", LawRuleType.weekly_overtime,
                     {"threshold_hours": 40, "multiplier": 1.5}),
            test_law("TEST.meal_break", LawRuleType.meal_break,
                     {"after_minutes": 300, "duration": 30, "paid": False,
                      "latest_start_minute_of_shift": None, "waivable_under_minutes": None}),
            test_law("TEST.rest_break", LawRuleType.rest_break,
                     {"per_minutes_worked": 360, "duration": 10, "paid": True}),
            test_law("TEST.minor_limits", LawRuleType.minor_limits,
                     {"age_min": 14, "age_max": 17, "school_week": True,
                      "max_hours_day": 8, "max_hours_week": 18,
                      "earliest_start": 420, "latest_end": 1140, "latest_end_summer": None}),
            test_law("TEST.minor_prohibited", LawRuleType.minor_prohibited_roles,
                     {"age_below": 18, "role_tags": ["powered_industrial_truck"]}),
        ],
    )


def emp(eid: str, name: str, age: int, roles: list[str], wage: float, **kw) -> Employee:
    return Employee(
        id=eid, name=name, phone="+15555550100", age=age, home_department_id="store",
        trained_role_ids=roles, status=EmploymentStatus.part_time, wage_per_hour=wage,
        hire_date=date(2024, 1, 1), **kw,
    )


def hard(cid: str, kind: ConstraintKind, params: dict, **kw) -> Constraint:
    return Constraint(id=cid, kind=kind, params=params, strength=Strength.hard,
                      source=Source.leader, status=RuleStatus.confirmed, **kw)


def build_config() -> StoreConfig:
    store = Store(
        id="tiny", name="Tiny Test Store", jurisdiction=JUR, slot_minutes=30,
        week_start=WEEK_START,
        hours=[DayHours(day=0, open=540, close=1020), DayHours(day=1, open=540, close=1020)],
    )
    roles = [
        Role(id="leader", department_id="store", name="Leader on duty", gap_penalty_per_hour=50),
        Role(id="cashier", department_id="store", name="Cashier", gap_penalty_per_hour=30),
        Role(id="stocker", department_id="store", name="Stocker", gap_penalty_per_hour=10),
        Role(id="pit_operator", department_id="store", name="Forklift", min_age=18,
             gap_penalty_per_hour=20),
    ]
    employees = [
        emp("e1", "Lee", 30, ["leader"], 25.0),
        emp("e2", "Cam", 22, ["cashier"], 15.0),
        emp("e3", "Sam", 19, ["cashier", "stocker"], 16.0),
        emp("e4", "Pat", 40, ["stocker", "pit_operator"], 18.0),
        emp("e5", "Mia", 16, ["cashier"], 14.0),
        emp("e6", "Jo", 35, ["leader", "cashier"], 24.0),
    ]
    demand = [
        DemandRequirement(id="d1", role_id="cashier", day=0, start=540, end=1020, headcount=1,
                          source=DemandSource.corporate),
        DemandRequirement(id="d2", role_id="leader", day=0, start=540, end=1020, headcount=1,
                          source=DemandSource.corporate),
        DemandRequirement(id="d3", role_id="cashier", day=1, start=540, end=780, headcount=1,
                          source=DemandSource.corporate),
    ]
    constraints = [
        hard("c_min_len", ConstraintKind.min_shift_length, {"minutes": 240}),
        hard("c_max_len", ConstraintKind.max_shift_length, {"minutes": 600}),
        hard("c_rest", ConstraintKind.min_rest_between_shifts, {"minutes": 600}),
        hard("c_days", ConstraintKind.max_days_per_week, {"days": 5}),
    ]
    return StoreConfig(
        store=store,
        departments=[Department(id="store", name="Store")],
        roles=roles,
        role_tags={"pit_operator": ["powered_industrial_truck"]},
        employees=employees,
        demand=demand,
        budget=Budget(weekly_hours_cap=30),
        constraints=constraints,
        law_pack=build_law_pack(),
    )


def simple_shift(sid: str, eid: str, day: int, start: int, end: int, role: str) -> Shift:
    return Shift(id=sid, employee_id=eid, day=day, start=start, end=end,
                 segments=[RoleSegment(role_id=role, start=start, end=end)])


def build_perfect_schedule() -> Schedule:
    """Hand calculation (see test_perfect_schedule_metrics_match_hand_calc):
    hours 4+4+4+4+4+7.5 = 27.5; wages 100+96+60+56+64+135 = 511; coverage 100%."""
    long_shift = Shift(
        id="s6", employee_id="e4", day=0, start=540, end=1020,
        breaks=[Break(start=660, end=690, kind="rest", paid=True),
                Break(start=780, end=810, kind="meal", paid=False)],
        segments=[RoleSegment(role_id="stocker", start=540, end=660),
                  RoleSegment(role_id="stocker", start=690, end=780),
                  RoleSegment(role_id="stocker", start=810, end=1020)],
    )
    return Schedule(
        store_id="tiny", week_start=WEEK_START, config_version=1, produced_by="hand",
        status="optimal",
        shifts=[
            simple_shift("s1", "e1", 0, 540, 780, "leader"),
            simple_shift("s2", "e6", 0, 780, 1020, "leader"),
            simple_shift("s3", "e2", 0, 540, 780, "cashier"),
            simple_shift("s4", "e5", 0, 780, 1020, "cashier"),
            simple_shift("s5", "e3", 1, 540, 780, "cashier"),
            long_shift,
        ],
    )


@pytest.fixture
def config() -> StoreConfig:
    return build_config()


@pytest.fixture
def perfect() -> Schedule:
    return build_perfect_schedule()


@pytest.fixture
def approved_at() -> datetime:
    return datetime(2026, 11, 6, 22, 0)


@pytest.fixture
def kit():
    """Helper builders for tests (conftest can't be imported directly under importlib mode)."""
    from types import SimpleNamespace

    return SimpleNamespace(
        simple_shift=simple_shift, hard=hard, test_law=test_law, emp=emp,
        build_config=build_config, build_perfect_schedule=build_perfect_schedule,
    )
