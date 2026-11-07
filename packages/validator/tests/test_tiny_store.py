"""tiny_store.json (WS4) + the real law pack (WS3 resolver) + WS4's hand-checked schedule."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shiftwright_contracts.models import (
    Break,
    RoleSegment,
    Schedule,
    Shift,
    StoreConfig,
    ViolationCode,
)
from shiftwright_validator import validate

laws = pytest.importorskip("shiftwright_laws")

FIXTURE = Path(__file__).resolve().parents[2] / "scenarios" / "fixtures" / "tiny_store.json"
V = ViolationCode
FRI, SAT = 4, 5


def h(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def shift(sid, eid, day, *pieces, breaks=()):
    """pieces: (role, 'HH:MM', 'HH:MM') back to back."""
    segments = [RoleSegment(role_id=r, start=h(a), end=h(b)) for r, a, b in pieces]
    return Shift(id=sid, employee_id=eid, day=day, start=segments[0].start, end=segments[-1].end,
                 segments=segments, breaks=list(breaks))


def load(state: str | None = None) -> StoreConfig:
    """Real law pack for the store's own jurisdiction (TX), or another state to test against."""
    config = StoreConfig.model_validate(json.loads(FIXTURE.read_text()))
    if state is not None:
        config.store.jurisdiction.state = state
    config.law_pack = laws.resolve(config.store.jurisdiction)
    return config


def ws4_hand_schedule(config: StoreConfig) -> Schedule:
    """The full-coverage schedule from packages/scenarios/STATUS.md (66 h)."""
    return Schedule(
        store_id=config.store.id, week_start=config.store.week_start, config_version=1,
        produced_by="hand:ws4", status="feasible",
        shifts=[
            shift("a1", "e1", FRI, ("leader_on_duty", "08:00", "14:00")),
            shift("a2", "e1", SAT, ("leader_on_duty", "08:00", "14:00")),
            shift("b1", "e2", FRI, ("leader_on_duty", "14:00", "20:00")),
            shift("b2", "e2", SAT, ("leader_on_duty", "14:00", "20:00")),
            shift("c1", "e3", FRI, ("cashier", "08:00", "14:00")),
            shift("c2", "e3", SAT, ("cashier", "14:00", "20:00")),
            shift("j1", "e4", FRI, ("cashier", "16:00", "20:00")),
            shift("j2", "e4", SAT, ("cashier", "08:00", "14:00")),
            shift("m2", "e5", SAT, ("pit_operator", "06:00", "09:00"), ("truck_unload", "09:00", "10:00")),
            shift("r1", "e6", FRI, ("cashier", "11:00", "19:00")),
            shift("r2", "e6", SAT, ("truck_unload", "06:00", "10:00"), ("cashier", "10:00", "14:00")),
        ],
    )


def test_ws4_hand_schedule_passes_in_texas():
    config = load()
    report = validate(config, ws4_hand_schedule(config))
    assert report.violations == [], [v.message for v in report.violations]
    m = report.recomputed_metrics
    assert m.total_hours == pytest.approx(66)
    # 12*26 + 12*25 + 12*15.5 + 10*15 + 4*18 + 16*16
    assert m.total_wage_cost == pytest.approx(1276.0)
    assert m.coverage_pct == pytest.approx(100.0)
    assert m.gap_penalty_dollars == 0 and m.soft_penalty_dollars == 0
    assert m.objective_dollars == pytest.approx(1276.0)


def test_pit_trap_minor_on_forklift():
    config = load()
    sched = ws4_hand_schedule(config)
    j2 = next(s for s in sched.shifts if s.id == "j2")
    j2.segments = [RoleSegment(role_id="pit_operator", start=h("08:00"), end=h("14:00"))]
    report = validate(config, sched)
    hits = [v for v in report.violations if v.code == V.minor_prohibited_role]
    assert hits and hits[0].law_rule_id == "US.minor_prohibited_roles.1"
    assert {v.code for v in report.violations} == {V.minor_prohibited_role}


def test_jordan_unavailable_friday_morning():
    config = load()
    sched = ws4_hand_schedule(config)
    j1 = next(s for s in sched.shifts if s.id == "j1")
    j1.start = h("14:00")
    j1.segments = [RoleSegment(role_id="cashier", start=h("14:00"), end=h("20:00"))]
    report = validate(config, sched)
    assert V.unavailable in {v.code for v in report.violations}


def test_not_together_is_priced():
    config = load()
    sched = ws4_hand_schedule(config)
    j1 = next(s for s in sched.shifts if s.id == "j1")
    j1.start = h("15:00")
    j1.segments = [RoleSegment(role_id="cashier", start=h("15:00"), end=h("20:00"))]
    c1 = next(s for s in sched.shifts if s.id == "c1")
    c1.end = h("16:00")
    c1.segments = [RoleSegment(role_id="cashier", start=h("08:00"), end=h("16:00"))]
    report = validate(config, sched)
    assert report.passed
    assert {v.code for v in report.violations} == {V.soft}
    assert report.recomputed_metrics.soft_penalty_dollars == pytest.approx(25.0)  # 1 h overlap


def test_california_needs_breaks_on_eight_hour_shifts():
    config = load("CA")
    sched = ws4_hand_schedule(config)
    codes = {v.code for v in validate(config, sched).violations}
    # Riley's 8 h shifts need a meal and rest breaks under the CA pack
    assert V.meal_break in codes and V.rest_break in codes
    # Add breaks to Riley's Friday shift and it is clean on that shift
    r1 = next(s for s in sched.shifts if s.id == "r1")
    r1.breaks = [Break(start=h("13:00"), end=h("13:30"), kind="rest", paid=True),
                 Break(start=h("15:00"), end=h("15:30"), kind="meal", paid=False),
                 Break(start=h("17:00"), end=h("17:30"), kind="rest", paid=True)]
    r1.segments = [RoleSegment(role_id="cashier", start=h("11:00"), end=h("13:00")),
                   RoleSegment(role_id="cashier", start=h("13:30"), end=h("15:00")),
                   RoleSegment(role_id="cashier", start=h("15:30"), end=h("17:00")),
                   RoleSegment(role_id="cashier", start=h("17:30"), end=h("19:00"))]
    remaining = [v for v in validate(config, sched).violations if v.start == h("11:00") and v.day == FRI]
    assert remaining == [], [v.message for v in remaining]
