"""Engine schedules pass WS2's validator with 0 hard violations and no metrics_mismatch."""
from __future__ import annotations

import pytest
from engine_fixtures import tiny_store, without
from shiftwright_contracts.models import (
    AvailabilityEntry,
    AvailabilityKind,
    Budget,
    Constraint,
    ConstraintKind,
    Jurisdiction,
    RuleStatus,
    Source,
    StoreConfig,
    Strength,
)
from shiftwright_engine import solve_week
from shiftwright_validator import validate


def soft(cid, kind, params, w, **kw):
    return Constraint(id=cid, kind=kind, params=params, strength=Strength.soft, weight_dollars=w,
                      source=Source.leader, status=RuleStatus.confirmed, **kw)


def soft_heavy(j: Jurisdiction | None = None) -> StoreConfig:
    cfg = without(tiny_store(j), "c_min_rest", "c_lod_always", "c_max_shift")
    emps = [e.model_copy(update={"availability": e.availability + [
        AvailabilityEntry(weekday=5, start=1080, end=1260, kind=AvailabilityKind.preferred_off, weight_dollars=3)]})
        if e.id == "e3" else e for e in cfg.employees]
    return cfg.model_copy(update={
        "employees": emps,
        "budget": Budget(weekly_hours_cap=90, overtime_allowed=True),
        "constraints": cfg.constraints + [
            soft("s_rest", ConstraintKind.min_rest_between_shifts, {"minutes": 720}, 4),
            soft("s_max", ConstraintKind.max_shift_length, {"minutes": 360}, 2),
            soft("s_lod", ConstraintKind.always_staffed, {"role_id": "leader_on_duty", "windows": "store_hours"}, 50),
            soft("s_pref", ConstraintKind.preferred_role, {"employee_id": "e1", "role_id": "cashier"}, 1),
            soft("s_close", ConstraintKind.fair_spread, {"shift_class": "close", "max_per_employee": 0}, 5),
            soft("s_days", ConstraintKind.max_days_per_week, {"days": 1}, 6),
        ]})


CASES = {
    "tx": lambda: tiny_store(),
    "ca_no_lod": lambda: without(tiny_store(Jurisdiction(state="CA")), "c_lod_always"),
    "tx_budget10": lambda: without(tiny_store(), "c_lod_always").model_copy(update={"budget": Budget(weekly_hours_cap=10)}),
    "tx_budget40": lambda: tiny_store().model_copy(update={"budget": Budget(weekly_hours_cap=40)}),
    "tx_soft_ot": lambda: soft_heavy(),
    "ca_soft_ot": lambda: soft_heavy(Jurisdiction(state="CA")),
}


@pytest.mark.parametrize("name", list(CASES))
def test_validator_agrees(name):
    cfg = CASES[name]()
    s = solve_week(cfg, time_limit_s=4)
    assert s.status in ("optimal", "feasible"), s.solver_stats
    r = validate(cfg, s)
    bad = [v.message for v in r.violations if v.severity == "hard" or v.code.value == "metrics_mismatch"]
    assert r.passed and bad == [], bad
    for f in ("total_hours", "total_wage_cost", "overtime_hours", "coverage_pct", "gap_penalty_dollars",
              "soft_penalty_dollars", "objective_dollars"):
        assert abs(getattr(s.metrics, f) - getattr(r.recomputed_metrics, f)) < 0.011, (f, s.metrics, r.recomputed_metrics)
