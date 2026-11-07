"""WS1 acceptance tests (from briefs/WS1-engine.md)."""
from __future__ import annotations

import time

from engine_fixtures import approved_at, tiny_store
from shiftwright_contracts.models import (
    Budget,
    BudgetApproval,
    Constraint,
    ConstraintKind,
    GapReasonCode,
    RuleStatus,
    Source,
    StoreConfig,
    Strength,
)
from shiftwright_engine import explain_gap, find_conflicts, solve_week

from selfcheck import hard_problems


def test_tiny_store_optimal_fast_and_clean():
    cfg = tiny_store()
    t0 = time.perf_counter()
    s = solve_week(cfg, time_limit_s=10)
    elapsed = time.perf_counter() - t0
    assert s.status == "optimal", s.solver_stats
    assert elapsed < 2.0, elapsed
    assert s.shifts
    assert hard_problems(cfg, s) == []
    assert s.metrics is not None
    assert s.metrics.budget_hours_used <= cfg.budget.weekly_hours_cap
    for g in s.gaps:
        assert g.penalty_dollars > 0


def test_nobody_trained_gives_full_penalty_gaps_with_no_reasons():
    cfg = tiny_store()
    emps = [e.model_copy(update={"trained_role_ids": [r for r in e.trained_role_ids if r != "cashier"]})
            for e in cfg.employees]
    cfg = cfg.model_copy(update={"employees": emps})
    s = solve_week(cfg, time_limit_s=10)
    assert s.status in ("optimal", "feasible")
    cash = [g for g in s.gaps if g.role_id == "cashier"]
    assert cash
    # every cashier headcount-hour is missing: 2 days * (10h*1 + 2h*1) * $30
    total = sum(g.penalty_dollars for g in cash)
    assert abs(total - 2 * 12 * 30) < 0.01
    assert all(g.reasons == [] for g in cash)


def test_cashier_gap_has_one_reason_per_trained_cashier():
    cfg = tiny_store()
    # Tight budget forces gaps while trained cashiers exist.
    cfg = cfg.model_copy(update={"budget": Budget(weekly_hours_cap=20)})
    s = solve_week(cfg, time_limit_s=10)
    trained = {e.id for e in cfg.employees if "cashier" in e.trained_role_ids}
    cash = [g for g in s.gaps if g.role_id == "cashier"]
    assert cash
    for g in cash:
        assert {r.employee_id for r in g.reasons} == trained
        assert len(g.reasons) == len(trained)
        assert explain_gap(cfg, s, g) == g.reasons


def test_minor_never_on_prohibited_role():
    cfg = tiny_store()
    s = solve_week(cfg, time_limit_s=10)
    for sh in s.shifts:
        if sh.employee_id == "minnie":
            assert all(seg.role_id != "pit_operator" for seg in sh.segments)
    # pit gaps (if any) cite minnie's minor rule
    for g in s.gaps:
        if g.role_id == "pit_operator":
            codes = {r.employee_id: r for r in g.reasons}
            assert codes["minnie"].code == GapReasonCode.minor_rule
            assert codes["minnie"].law_rule_id == "TEST.minor_prohibited_roles.1"


def test_budget_cap_10_hours():
    cfg = tiny_store()
    cfg = cfg.model_copy(update={"budget": Budget(weekly_hours_cap=10)})
    s = solve_week(cfg, time_limit_s=10)
    assert s.status in ("optimal", "feasible")
    assert s.metrics.total_hours <= 10 + 1e-6
    assert s.gaps and all(g.penalty_dollars > 0 for g in s.gaps)
    assert hard_problems(cfg, s) == []


def test_budget_approval_raises_cap():
    cfg = tiny_store()
    cfg = cfg.model_copy(update={"budget": Budget(
        weekly_hours_cap=10,
        approvals=[BudgetApproval(id="a1", extra_hours=8, reason="truck", approved_by="lead",
                                  approved_at=approved_at())])})
    s = solve_week(cfg, time_limit_s=10)
    assert 10 < s.metrics.total_hours <= 18 + 1e-6


def test_contradictory_hard_set_is_infeasible():
    cfg = tiny_store()
    bad = Constraint(id="c-always-ghost", kind=ConstraintKind.always_staffed,
                     params={"role_id": "ghost_role", "windows": "store_hours"},
                     strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed)
    cfg = cfg.model_copy(update={"constraints": cfg.constraints + [bad]})
    s = solve_week(cfg, time_limit_s=10)
    assert s.status == "infeasible"
    assert "c-always-ghost" in s.infeasibility.conflicting_constraint_ids
    inf = find_conflicts(cfg)
    assert inf is not None and "c-always-ghost" in inf.conflicting_constraint_ids
    assert find_conflicts(tiny_store()) is None


def test_always_staffed_role_without_trained_staff_is_infeasible():
    cfg = tiny_store()
    emps = [e.model_copy(update={"trained_role_ids": [r for r in e.trained_role_ids if r != "lod"]})
            for e in cfg.employees]
    rule = Constraint(id="c-lod", kind=ConstraintKind.always_staffed,
                      params={"role_id": "lod", "windows": "store_hours"},
                      strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed)
    cfg = cfg.model_copy(update={"employees": emps, "constraints": cfg.constraints + [rule]})
    s = solve_week(cfg, time_limit_s=10)
    assert s.status == "infeasible"
    assert s.infeasibility.conflicting_constraint_ids == ["c-lod"]


def test_provisional_constraints_are_ignored():
    cfg = tiny_store()
    bad = Constraint(id="c-prov", kind=ConstraintKind.always_staffed,
                     params={"role_id": "ghost_role", "windows": "store_hours"},
                     strength=Strength.hard, source=Source.inferred, status=RuleStatus.provisional,
                     evidence="test")
    cfg = cfg.model_copy(update={"constraints": cfg.constraints + [bad]})
    assert solve_week(cfg, time_limit_s=10).status == "optimal"


def _roundtrip(cfg: StoreConfig) -> StoreConfig:
    return StoreConfig.model_validate_json(cfg.model_dump_json())


def test_schedule_serializes():
    cfg = _roundtrip(tiny_store())
    s = solve_week(cfg, time_limit_s=10)
    assert s.model_dump_json()
