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


def demo_like_store(n_staff: int = 60, seed: int = 7) -> StoreConfig:
    """Synthetic ~demo-size store (7 days, 30-min slots). Used for performance tests until
    WS4's demo_store.json lands. Numbers are arbitrary test values."""
    import random

    rng = random.Random(seed)
    base = tiny_store()
    store = base.store.model_copy(update={
        "id": "demo-like",
        "hours": [DayHours(day=d, open=8 * 60, close=22 * 60) for d in range(7)],
    })
    roles = base.roles + [
        Role(id="fulfillment", department_id="fos", name="Fulfillment", gap_penalty_per_hour=25),
        Role(id="ap", department_id="fos", name="Asset protection", gap_penalty_per_hour=35),
    ]
    role_ids = [r.id for r in roles]
    emps = []
    for i in range(n_staff):
        k = rng.choice([1, 2, 2, 3])
        tr = rng.sample(role_ids, k)
        ft = rng.random() < 0.4
        emps.append(emp(f"e{i:02d}", tr, age=rng.choice([17] + [25] * 9), wage=round(rng.uniform(13, 22), 2),
                        status=EmploymentStatus.full_time if ft else EmploymentStatus.part_time,
                        max_h=40 if ft else 28))
    demand = []
    for d in range(7):
        busy = 1 if d in (4, 5, 6) else 0
        demand += [
            DemandRequirement(id=f"{d}-c1", role_id="cashier", day=d, start=480, end=1320, headcount=3 + busy,
                              source=DemandSource.corporate),
            DemandRequirement(id=f"{d}-c2", role_id="cashier", day=d, start=1020, end=1200, headcount=2,
                              source=DemandSource.corporate),
            DemandRequirement(id=f"{d}-s", role_id="stocker", day=d, start=420, end=960, headcount=3,
                              source=DemandSource.corporate),
            DemandRequirement(id=f"{d}-l", role_id="lod", day=d, start=480, end=1320, headcount=1,
                              source=DemandSource.corporate),
            DemandRequirement(id=f"{d}-f", role_id="fulfillment", day=d, start=540, end=1140, headcount=2,
                              source=DemandSource.corporate),
            DemandRequirement(id=f"{d}-a", role_id="ap", day=d, start=600, end=1320, headcount=1,
                              source=DemandSource.corporate),
        ]
        if d in (1, 4):
            demand.append(DemandRequirement(id=f"{d}-pit", role_id="pit_operator", day=d, start=360 + 60,
                                            end=720, headcount=2, source=DemandSource.event))
    return base.model_copy(update={
        "store": store, "roles": roles, "employees": emps, "demand": demand,
        "budget": Budget(weekly_hours_cap=1500),
        "constraints": base.constraints + [
            Constraint(id="c-rest", kind=ConstraintKind.min_rest_between_shifts, params={"minutes": 600},
                       strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed),
            Constraint(id="c-days", kind=ConstraintKind.max_days_per_week, params={"days": 5},
                       strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed),
        ],
    })
