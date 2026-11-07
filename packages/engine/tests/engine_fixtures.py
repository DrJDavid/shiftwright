"""Hand-made test stores for engine tests.

These are NOT real labor law. Every LawRule here uses clearly fake/test values and a
placeholder citation, so tests never depend on facts stated from memory.
"""
from __future__ import annotations

from datetime import date, datetime

from shiftwright_contracts.models import (
    Budget,
    Citation,
    Constraint,
    ConstraintKind,
    DayHours,
    DemandRequirement,
    DemandSource,
    Department,
    EmploymentStatus,
    Employee,
    Jurisdiction,
    LawPack,
    LawRule,
    LawRuleType,
    Role,
    RuleStatus,
    Source,
    Store,
    StoreConfig,
    Strength,
)

TEST_CITATION = Citation(
    url="https://example.invalid/test-law",
    title="TEST ONLY - not real law",
    excerpt="Fabricated value for unit tests.",
    last_verified=date(2026, 1, 1),
)
JUR = Jurisdiction(state="ZZ")


def law(rule_id: str, type_: LawRuleType, params: dict) -> LawRule:
    return LawRule(
        id=rule_id,
        jurisdiction=JUR,
        level="state",
        type=type_,
        params=params,
        summary="TEST rule (fake values).",
        citation=TEST_CITATION,
        confidence="low",
    )


def test_law_pack() -> LawPack:
    return LawPack(
        jurisdiction=JUR,
        coverage="full",
        rules=[
            law("TEST.weekly_overtime.1", LawRuleType.weekly_overtime,
                {"threshold_hours": 40, "multiplier": 1.5}),
            law("TEST.meal_break.1", LawRuleType.meal_break,
                {"after_minutes": 360, "duration": 30, "paid": False,
                 "latest_start_minute_of_shift": None, "waivable_under_minutes": None}),
            law("TEST.minor_prohibited_roles.1", LawRuleType.minor_prohibited_roles,
                {"age_below": 18, "role_tags": ["test_hazard_tag"]}),
            law("TEST.minor_limits.1", LawRuleType.minor_limits,
                {"age_min": 16, "age_max": 17, "school_week": True,
                 "max_hours_day": 8, "max_hours_week": 30,
                 "earliest_start": None, "latest_end": 1320, "latest_end_summer": None}),
        ],
    )


def emp(eid: str, roles: list[str], *, age: int = 30, wage: float = 15.0,
        status: EmploymentStatus = EmploymentStatus.part_time, max_h: float = 40.0,
        **kw) -> Employee:
    return Employee(
        id=eid, name=eid.title(), phone="+15550000000", age=age,
        home_department_id="fos", trained_role_ids=roles, status=status,
        wage_per_hour=wage, max_hours_week=max_h, hire_date=date(2024, 1, 1), **kw,
    )


def tiny_store(**overrides) -> StoreConfig:
    """6 employees, 4 roles, 2 open days (Mon, Tue), 30-min slots."""
    store = Store(
        id="tiny", name="Tiny Test Store", jurisdiction=JUR, slot_minutes=30,
        week_start=date(2026, 11, 9),
        hours=[DayHours(day=0, open=8 * 60, close=18 * 60),
               DayHours(day=1, open=8 * 60, close=18 * 60)],
        pre_open_minutes=60, post_close_minutes=60,
    )
    roles = [
        Role(id="cashier", department_id="fos", name="Cashier", gap_penalty_per_hour=30),
        Role(id="stocker", department_id="fos", name="Stocker", gap_penalty_per_hour=20),
        Role(id="lod", department_id="fos", name="Leader on duty", gap_penalty_per_hour=60),
        Role(id="pit_operator", department_id="fos", name="PIT operator", min_age=0,
             gap_penalty_per_hour=40),
    ]
    employees = [
        emp("alice", ["cashier", "lod"], wage=20, status=EmploymentStatus.full_time),
        emp("bob", ["cashier", "stocker"], wage=15),
        emp("carol", ["stocker", "pit_operator"], wage=17),
        emp("dan", ["cashier"], wage=14),
        emp("erin", ["lod", "stocker"], wage=22, status=EmploymentStatus.full_time),
        emp("minnie", ["cashier", "pit_operator"], age=17, wage=12),
    ]
    demand = []
    for d in (0, 1):
        demand += [
            DemandRequirement(id=f"d{d}-cash", role_id="cashier", day=d, start=480, end=1080,
                              headcount=1, source=DemandSource.corporate),
            DemandRequirement(id=f"d{d}-cash-pm", role_id="cashier", day=d, start=960, end=1080,
                              headcount=1, source=DemandSource.corporate),
            DemandRequirement(id=f"d{d}-stock", role_id="stocker", day=d, start=420, end=720,
                              headcount=1, source=DemandSource.corporate),
            DemandRequirement(id=f"d{d}-lod", role_id="lod", day=d, start=480, end=1080,
                              headcount=1, source=DemandSource.corporate),
            DemandRequirement(id=f"d{d}-pit", role_id="pit_operator", day=d, start=420, end=600,
                              headcount=1, source=DemandSource.event),
        ]
    cfg = StoreConfig(
        store=store,
        departments=[Department(id="fos", name="Front of Store")],
        roles=roles,
        role_tags={"pit_operator": ["test_hazard_tag"]},
        employees=employees,
        demand=demand,
        budget=Budget(weekly_hours_cap=200),
        constraints=[
            Constraint(id="c-minlen", kind=ConstraintKind.min_shift_length,
                       params={"minutes": 240}, strength=Strength.hard,
                       source=Source.leader, status=RuleStatus.confirmed),
            Constraint(id="c-maxlen", kind=ConstraintKind.max_shift_length,
                       params={"minutes": 540}, strength=Strength.hard,
                       source=Source.leader, status=RuleStatus.confirmed),
        ],
        law_pack=test_law_pack(),
    )
    return cfg.model_copy(update=overrides)


def approved_at() -> datetime:
    return datetime(2026, 11, 6, 12, 0)
