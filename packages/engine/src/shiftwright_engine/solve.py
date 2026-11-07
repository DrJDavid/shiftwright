"""solve_week and find_conflicts."""
from __future__ import annotations

import time
from typing import Optional

from ortools.sat.python import cp_model

from shiftwright_contracts.models import Infeasibility, Schedule, StoreConfig

from .explain import explain_with_prep
from .model import Builder, solve
from .output import (
    availability_violations,
    compute_metrics,
    gaps_from_shifts,
    shifts_from_solution,
    soft_from_solution,
)
from .prep import SCALE, build_prep

STATUS = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible", cp_model.INFEASIBLE: "infeasible"}


def _base(config: StoreConfig, status: str, **kw) -> Schedule:
    return Schedule(store_id=config.store.id, week_start=config.store.week_start,
                    config_version=config.config_version, produced_by="engine", status=status, **kw)


def solve_week(config: StoreConfig, time_limit_s: float = 20, previous: Optional[Schedule] = None) -> Schedule:
    t0 = time.perf_counter()
    p = build_prep(config)
    built = Builder(p).build()
    t_build = time.perf_counter() - t0
    solver, status = solve(built, time_limit_s)
    stats = {
        "solver_status": solver.status_name(status),
        "build_s": round(t_build, 3),
        "solve_s": round(solver.wall_time, 3),
        "num_candidate_shifts": len(built.y),
        "num_role_vars": len(built.x),
        "notes": list(p.notes),
    }
    if status == cp_model.INFEASIBLE:
        inf = find_conflicts(config, time_limit_s=max(5.0, time_limit_s / 2))
        if inf is None:
            inf = Infeasibility(summary="The solver proved the hard rules cannot all hold, but could not "
                                        "isolate which ones within the time limit.")
        return _base(config, "infeasible", infeasibility=inf, solver_stats=stats)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        stats["error"] = "No schedule found within the time limit."
        return _base(config, "error", solver_stats=stats)

    shifts = shifts_from_solution(built, solver)
    soft = soft_from_solution(built, solver) + availability_violations(p, shifts)
    gaps = gaps_from_shifts(p, shifts)
    sched = _base(config, STATUS[status], shifts=shifts, soft_violations=soft)
    for g in gaps:
        g.reasons = explain_with_prep(p, sched, g)
    sched.gaps = gaps
    sched.metrics = compute_metrics(p, shifts, soft, gaps)
    obj = solver.objective_value + built.objective_const_units
    bound = solver.best_objective_bound + built.objective_const_units
    stats.update({
        "objective_dollars_incl_tiebreaks": round(obj / SCALE, 2),
        "best_bound_dollars": round(bound / SCALE, 2),
        "relative_gap": round((obj - bound) / obj, 6) if obj else 0.0,
        "total_s": round(time.perf_counter() - t0, 3),
    })
    sched.solver_stats = stats
    return sched


def find_conflicts(config: StoreConfig, time_limit_s: float = 10) -> Optional[Infeasibility]:
    """Hard-only feasibility check. None if the hard rules can all hold."""
    p = build_prep(config)
    built = Builder(p, assume=True).build()
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_workers = 1  # assumption cores are most reliable single-threaded
    status = solver.solve(built.model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    if status != cp_model.INFEASIBLE:
        return Infeasibility(conflicting_other=["solver_timeout"],
                             summary="Could not decide within the time limit whether the hard rules can all hold.")
    core = solver.sufficient_assumptions_for_infeasibility()
    lits = {lit.index: key for lit, key in built.assumptions.items()}
    cons, laws, other = [], [], []
    for idx in core:
        bucket, ident = lits[idx]
        {"constraint": cons, "law": laws, "other": other}[bucket].append(ident)
    names = {c.id: (c.note or c.kind.value) for c in config.constraints}
    parts = [f"rule {i} ({names.get(i, '')})" for i in cons] + [f"law {i}" for i in laws] + other
    summary = ("These hard rules cannot all hold together: " + "; ".join(parts) + "."
               if parts else "The hard rules cannot all hold, even before any rule-level assumptions "
                             "(check training, availability and store hours).")
    return Infeasibility(conflicting_constraint_ids=sorted(cons), conflicting_law_rule_ids=sorted(laws),
                         conflicting_other=sorted(other), summary=summary)
