"""Engine test fixtures.

`tiny_store()` is WS4's packages/scenarios/fixtures/tiny_store.json with the law pack resolved by
WS3 (`shiftwright_laws.resolve`). No law values are written here.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from shiftwright_contracts.models import (
    Budget,
    Constraint,
    ConstraintKind,
    DayHours,
    DemandRequirement,
    DemandSource,
    EmploymentStatus,
    Employee,
    Jurisdiction,
    Role,
    RuleStatus,
    Source,
    StoreConfig,
    Strength,
)
from shiftwright_laws import resolve

ROOT = Path(__file__).resolve().parents[3]
TINY = ROOT / "packages/scenarios/fixtures/tiny_store.json"


def with_law(cfg: StoreConfig, jurisdiction: Jurisdiction | None = None) -> StoreConfig:
    j = jurisdiction or cfg.store.jurisdiction
    store = cfg.store.model_copy(update={"jurisdiction": j})
    return cfg.model_copy(update={"store": store, "law_pack": resolve(j)})


def tiny_store(jurisdiction: Jurisdiction | None = None) -> StoreConfig:
    return with_law(StoreConfig.model_validate_json(TINY.read_text()), jurisdiction)


def without(cfg: StoreConfig, *constraint_ids: str) -> StoreConfig:
    return cfg.model_copy(update={"constraints": [c for c in cfg.constraints if c.id not in constraint_ids]})


def emp(eid: str, roles: list[str], *, age: int = 30, wage: float = 15.0,
        status: EmploymentStatus = EmploymentStatus.part_time, max_h: float = 40.0) -> Employee:
    from datetime import date

    return Employee(id=eid, name=eid.title(), phone="+15550000000", age=age,
                    home_department_id="front_of_store", trained_role_ids=roles, status=status,
                    wage_per_hour=wage, max_hours_week=max_h, hire_date=date(2024, 1, 1))


def approved_at() -> datetime:
    return datetime(2026, 11, 6, 12, 0)


def demo_like_store(n_staff: int = 60, seed: int = 7) -> StoreConfig:
    """Synthetic ~demo-size store (7 days, 30-min slots). Used for performance tests until
    WS4's demo_store.json lands. Numbers are arbitrary test values."""
    import random

    rng = random.Random(seed)
    base = without(tiny_store(), "c_jordan_casey", "c_lod_always", "c_min_rest")
    store = base.store.model_copy(update={
        "id": "demo-like", "pre_open_minutes": 60,
        "hours": [DayHours(day=d, open=8 * 60, close=22 * 60) for d in range(7)],
    })
    roles = base.roles + [
        Role(id="stocker", department_id="front_of_store", name="Stocker", gap_penalty_per_hour=20),
        Role(id="fulfillment", department_id="front_of_store", name="Fulfillment", gap_penalty_per_hour=25),
        Role(id="ap", department_id="front_of_store", name="Asset protection", gap_penalty_per_hour=35),
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
            DemandRequirement(id=f"{d}-l", role_id="leader_on_duty", day=d, start=480, end=1320, headcount=1,
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
