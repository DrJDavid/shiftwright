"""Adapters to other workstreams' public functions, with stubs until they land.

Each adapter looks the real function up at CALL time, so once WS1/WS2/WS3/WS8 merge to main
the API picks them up with no change here. `active_stubs()` reports which are still stubbed
(shown in /api/health and STATUS.md).

Stubs never invent facts:
  * engine stub: no shifts; every demand slot is reported as a priced gap (coverage computed).
  * validator stub: only certifies schedules with no shifts; otherwise refuses (StubUnavailable).
  * labor law: no stub — the real WS3 resolver (`shiftwright_laws.resolve`) is always used.
  * mine_patterns stub: [] (as the brief says).
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Optional

from shiftwright_laws import resolve as _laws_resolve

from shiftwright_contracts.models import (
    FixPlan,
    FixRequest,
    Gap,
    GapReason,
    Infeasibility,
    Jurisdiction,
    LawPack,
    Schedule,
    ScheduleMetrics,
    StoreConfig,
    ValidationReport,
)


class StubUnavailable(RuntimeError):
    """A stubbed dependency cannot answer this honestly."""


def _lookup(candidates: list[tuple[str, str]]) -> Optional[Callable[..., Any]]:
    for module, name in candidates:
        try:
            fn = getattr(importlib.import_module(module), name, None)
        except ImportError:
            fn = None
        if callable(fn):
            return fn
    return None


_ENGINE = "shiftwright_engine"
_SOLVE = [(_ENGINE, "solve_week"), (f"{_ENGINE}.solve", "solve_week")]
_FIX = [(_ENGINE, "fix_day"), (f"{_ENGINE}.fix", "fix_day")]
_EXPLAIN = [(_ENGINE, "explain_gap"), (f"{_ENGINE}.explain", "explain_gap")]
_CONFLICTS = [(_ENGINE, "find_conflicts"), (f"{_ENGINE}.conflicts", "find_conflicts")]
_VALIDATE = [("shiftwright_validator", "validate"), ("shiftwright_validator.validate", "validate")]
_MINE = [("shiftwright_insights", "mine_patterns"), ("shiftwright_insights.mine", "mine_patterns")]

_ALL = {
    "engine.solve_week": _SOLVE,
    "engine.fix_day": _FIX,
    "engine.explain_gap": _EXPLAIN,
    "engine.find_conflicts": _CONFLICTS,
    "validator.validate": _VALIDATE,
    "insights.mine_patterns": _MINE,
}


def active_stubs() -> list[str]:
    return [name for name, cands in _ALL.items() if _lookup(cands) is None]


# --------------------------------------------------------------------------- #
def solve_week(config: StoreConfig, time_limit_s: float = 20, previous: Schedule | None = None) -> Schedule:
    from .rules import usable

    config, notes = usable(config)  # an incomplete rule is set aside with a note, never a failed build
    fn = _lookup(_SOLVE)
    sched = fn(config, time_limit_s=time_limit_s, previous=previous) if fn else _stub_solve(config)
    if notes:
        stats = dict(sched.solver_stats or {})
        stats["notes"] = list(stats.get("notes") or []) + notes
        sched = sched.model_copy(update={"solver_stats": stats})
    return sched


def fix_day(req: FixRequest, time_limit_s: float = 8) -> FixPlan:
    fn = _lookup(_FIX)
    if fn:
        return fn(req, time_limit_s=time_limit_s)
    raise StubUnavailable("Call-out fixer (engine.fix_day) has not landed yet.")


def explain_gap(config: StoreConfig, schedule: Schedule, gap: Gap) -> list[GapReason]:
    fn = _lookup(_EXPLAIN)
    if fn:
        return fn(config, schedule, gap)
    return list(gap.reasons)  # engine fills these in solve_week; never invent more


def find_conflicts(config: StoreConfig) -> Infeasibility | None:
    fn = _lookup(_CONFLICTS)
    if fn:
        return fn(config)
    return None


def validate(config: StoreConfig, schedule: Schedule) -> ValidationReport:
    fn = _lookup(_VALIDATE)
    if fn:
        return fn(config, schedule)
    if schedule.shifts:
        raise StubUnavailable("Validator (WS2) has not landed yet; cannot check a schedule with shifts.")
    metrics = schedule.metrics or _stub_metrics(config, [])
    return ValidationReport(passed=True, hard_count=0, violations=[], recomputed_metrics=metrics)


def resolve_law(jurisdiction: Jurisdiction) -> LawPack:
    return _laws_resolve(jurisdiction)


def mine_patterns(config: StoreConfig, history: list[Schedule]) -> list:
    fn = _lookup(_MINE)
    if fn:
        return fn(config, history)
    return []


# --------------------------------------------------------------------------- #
# Engine stub
# --------------------------------------------------------------------------- #
def _stub_metrics(config: StoreConfig, gaps: list[Gap]) -> ScheduleMetrics:
    gap_pen = round(sum(g.penalty_dollars for g in gaps), 2)
    required = sum(d.headcount * (d.end - d.start) / 60 for d in config.demand)
    cap = config.budget.weekly_hours_cap + sum(a.extra_hours for a in config.budget.approvals)
    return ScheduleMetrics(
        total_hours=0.0,
        total_wage_cost=0.0,
        overtime_hours=0.0,
        coverage_pct=0.0 if required > 0 else 100.0,
        gap_penalty_dollars=gap_pen,
        soft_penalty_dollars=0.0,
        objective_dollars=gap_pen,
        budget_hours_cap=cap,
        budget_hours_used=0.0,
    )


def _stub_solve(config: StoreConfig) -> Schedule:
    penalty = {r.id: r.gap_penalty_per_hour for r in config.roles}
    gaps = [
        Gap(
            role_id=d.role_id,
            day=d.day,
            start=d.start,
            end=d.end,
            missing_headcount=d.headcount,
            penalty_dollars=round(d.headcount * (d.end - d.start) / 60 * penalty.get(d.role_id, 0.0), 2),
            reasons=[],
        )
        for d in config.demand
        if d.headcount > 0
    ]
    return Schedule(
        store_id=config.store.id,
        week_start=config.store.week_start,
        config_version=config.config_version,
        produced_by="stub:engine",
        status="feasible",
        shifts=[],
        gaps=gaps,
        metrics=_stub_metrics(config, gaps),
        solver_stats={"stub": True, "note": "WS1 engine not merged yet; no shifts are created."},
    )
