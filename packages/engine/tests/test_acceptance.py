"""WS1 acceptance tests (from briefs/WS1-engine.md), on WS4's tiny_store.json + WS3's law pack."""
from __future__ import annotations

import time

from engine_fixtures import approved_at, tiny_store, without
from selfcheck import hard_problems
from shiftwright_contracts.models import (
    Budget,
    BudgetApproval,
    Constraint,
    ConstraintKind,
    GapReasonCode,
    Jurisdiction,
    RuleStatus,
    Source,
    StoreConfig,
    Strength,
)
from shiftwright_engine import explain_gap, find_conflicts, solve_week

CASHIERS = {"e1", "e3", "e4", "e6"}


def _budget(cfg: StoreConfig, hours: float, **kw) -> StoreConfig:
    return cfg.model_copy(update={"budget": Budget(weekly_hours_cap=hours, **kw)})


def test_tiny_store_optimal_fast_and_clean():
    cfg = tiny_store()
    assert cfg.law_pack is not None and cfg.law_pack.coverage == "full"
    t0 = time.perf_counter()
    s = solve_week(cfg, time_limit_s=10)
    elapsed = time.perf_counter() - t0
    assert s.status == "optimal", s.solver_stats
    assert elapsed < 2.0, elapsed
    assert hard_problems(cfg, s) == []
    # WS4's hand check: a full-coverage schedule within the 70 h cap exists.
    assert s.metrics.coverage_pct == 100.0
    assert s.gaps == []
    assert s.metrics.budget_hours_used <= 70


def test_nobody_trained_gives_full_penalty_gaps_with_no_reasons():
    cfg = tiny_store()
    emps = [e.model_copy(update={"trained_role_ids": [r for r in e.trained_role_ids if r != "cashier"]})
            for e in cfg.employees]
    cfg = cfg.model_copy(update={"employees": emps})
    s = solve_week(cfg, time_limit_s=10)
    assert s.status in ("optimal", "feasible")
    cash = [g for g in s.gaps if g.role_id == "cashier"]
    # 32 cashier headcount-hours (WS4 hand check) at $60/h
    assert abs(sum(g.penalty_dollars for g in cash) - 32 * 60) < 0.01
    assert all(g.reasons == [] for g in cash)


def test_cashier_gap_has_one_reason_per_trained_cashier():
    cfg = _budget(tiny_store(), 40)  # leader-on-duty alone takes 24 h (hard), so cashier gaps appear
    s = solve_week(cfg, time_limit_s=10)
    assert s.status == "optimal"
    cash = [g for g in s.gaps if g.role_id == "cashier"]
    assert cash
    for g in cash:
        assert sorted(r.employee_id for r in g.reasons) == sorted(CASHIERS)
        assert explain_gap(cfg, s, g) == g.reasons
    codes = {r.code for g in cash for r in g.reasons}
    assert GapReasonCode.budget_cap in codes or GapReasonCode.already_assigned in codes


def test_minor_never_on_pit_and_reason_cites_law():
    cfg = tiny_store()
    e4 = next(e for e in cfg.employees if e.id == "e4")
    assert e4.age == 17 and "pit_operator" in e4.trained_role_ids
    s = solve_week(cfg, time_limit_s=10)
    assert not any(seg.role_id == "pit_operator" for sh in s.shifts if sh.employee_id == "e4" for seg in sh.segments)
    # Force a PIT gap (no adult PIT operator) and check e4's reason.
    emps = [e.model_copy(update={"trained_role_ids": ["truck_unload"]}) if e.id == "e5" else e for e in cfg.employees]
    s = solve_week(cfg.model_copy(update={"employees": emps}), time_limit_s=10)
    pit = [g for g in s.gaps if g.role_id == "pit_operator"]
    assert pit
    for g in pit:
        (r,) = g.reasons
        assert r.employee_id == "e4" and r.code == GapReasonCode.minor_rule
        assert r.law_rule_id == "US.minor_prohibited_roles.1"


def test_budget_cap_10_hours():
    cfg = _budget(without(tiny_store(), "c_lod_always"), 10)
    s = solve_week(cfg, time_limit_s=10)
    assert s.status == "optimal"
    assert s.metrics.total_hours <= 10 + 1e-6
    assert s.gaps and all(g.penalty_dollars > 0 for g in s.gaps)
    assert hard_problems(cfg, s) == []


def test_budget_cap_below_always_staffed_is_infeasible_with_both_named():
    s = solve_week(_budget(tiny_store(), 10), time_limit_s=10)
    assert s.status == "infeasible"
    assert s.infeasibility.conflicting_constraint_ids == ["c_lod_always"]
    assert "budget.weekly_hours_cap" in s.infeasibility.conflicting_other


def test_budget_approval_raises_cap():
    cfg = _budget(without(tiny_store(), "c_lod_always"), 10, approvals=[
        BudgetApproval(id="a1", extra_hours=8, reason="truck", approved_by="lead", approved_at=approved_at())])
    s = solve_week(cfg, time_limit_s=10)
    assert 10 < s.metrics.total_hours <= 18 + 1e-6
    assert s.metrics.budget_hours_cap == 18


def test_contradictory_hard_set_is_infeasible():
    bad = Constraint(id="c-always-ghost", kind=ConstraintKind.always_staffed,
                     params={"role_id": "ghost_role", "windows": "store_hours"},
                     strength=Strength.hard, source=Source.leader, status=RuleStatus.confirmed)
    cfg = tiny_store()
    cfg = cfg.model_copy(update={"constraints": cfg.constraints + [bad]})
    s = solve_week(cfg, time_limit_s=10)
    assert s.status == "infeasible"
    assert s.infeasibility.conflicting_constraint_ids == ["c-always-ghost"]
    assert find_conflicts(tiny_store()) is None


def test_always_staffed_role_without_trained_staff_is_infeasible():
    cfg = tiny_store()
    emps = [e.model_copy(update={"trained_role_ids": [r for r in e.trained_role_ids if r != "leader_on_duty"]})
            for e in cfg.employees]
    s = solve_week(cfg.model_copy(update={"employees": emps}), time_limit_s=10)
    assert s.status == "infeasible"
    assert s.infeasibility.conflicting_constraint_ids == ["c_lod_always"]


def test_provisional_constraints_are_ignored():
    bad = Constraint(id="c-prov", kind=ConstraintKind.always_staffed,
                     params={"role_id": "ghost_role", "windows": "store_hours"},
                     strength=Strength.hard, source=Source.inferred, status=RuleStatus.provisional,
                     evidence="test")
    cfg = tiny_store()
    assert solve_week(cfg.model_copy(update={"constraints": cfg.constraints + [bad]}), time_limit_s=10).status == "optimal"


def test_california_pack_breaks_and_daily_overtime():
    # Without c_lod_always: with only two leaders, CA's rest breaks (rounded up to 30-min slots and
    # placed at fixed positions) make "leader always on duty" infeasible. See STATUS.md.
    cfg = without(tiny_store(Jurisdiction(state="CA")), "c_lod_always")
    s = solve_week(cfg, time_limit_s=10)
    assert s.status == "optimal"
    assert hard_problems(cfg, s) == []
    meal = [r for r in cfg.law_pack.rules if r.type.value == "meal_break"]
    first = min(meal, key=lambda r: r.params["after_minutes"])
    daily_thr = next(r for r in cfg.law_pack.rules if r.type.value == "daily_overtime").params["threshold_hours"] * 60
    for sh in s.shifts:
        length = sh.end - sh.start
        if length > first.params["after_minutes"]:
            meals = [b for b in sh.breaks if b.kind == "meal"]
            assert meals and meals[0].end - sh.start <= first.params["latest_start_minute_of_shift"]
        # overtime not allowed -> no shift above the daily OT threshold (paid hours)
        paid = length - sum(b.end - b.start for b in sh.breaks if not b.paid)
        assert paid <= daily_thr
    assert s.metrics.overtime_hours == 0


def test_schedule_roundtrips_json():
    s = solve_week(tiny_store(), time_limit_s=10)
    assert type(s).model_validate_json(s.model_dump_json()) == s
