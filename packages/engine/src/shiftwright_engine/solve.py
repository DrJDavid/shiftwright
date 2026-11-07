"""solve_week and find_conflicts."""
from __future__ import annotations

import time
from typing import Optional

from ortools.sat.python import cp_model

from shiftwright_contracts.models import Infeasibility, Schedule, StoreConfig

from .explain import explain_with_prep
from .greedy import greedy
from .model import Builder, Built, solve
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


SINGLE_STAGE_MAX_CANDS = 8_000  # below this, solve the full 30-min grid directly
COARSE_STEPS = ((60, 60), (60, 120), (120, 120))  # (start step, length step) tried for stage A
COARSE_MAX_CANDS = 20_000
STRATEGY = "greedy"  # large models: "greedy" hint, or "coarse" two-stage


def _coarse_filter(p, start_step: int, length_step: int):
    lo = {eid: p.shift_bounds(eid)[0] for eid in p.emps}

    def ok(c) -> bool:
        w0 = p.windows[c.day][0]
        w0 -= w0 % p.slot  # first grid start in the window
        return (c.start - w0) % start_step == 0 and (c.end - c.start - lo[c.emp]) % length_step == 0
    return ok


def _hint_from(src: Built, solver: cp_model.CpSolver, dst: Built) -> dict:
    hint = {v: 0 for v in dst.y.values()}
    for idx, v in src.y.items():
        if solver.boolean_value(v) and idx in dst.y:
            hint[dst.y[idx]] = 1
    for k, v in dst.x.items():
        sv = src.x.get(k)
        hint[v] = int(solver.boolean_value(sv)) if sv is not None else 0
    return hint


def solve_week(config: StoreConfig, time_limit_s: float = 20, previous: Optional[Schedule] = None) -> Schedule:
    """Two-stage when the candidate set is large:
      A. solve a coarse candidate grid (hourly starts/lengths) to get a good schedule fast;
      B. solve the full slot grid, hinted with A's schedule (A's shifts are a subset of B's).
    Then phase 2 re-assigns roles with the churn tiebreak on the chosen shifts."""
    t0 = time.perf_counter()
    deadline = t0 + time_limit_s
    p = build_prep(config)
    stats: dict = {"num_candidate_shifts": len(p.cands), "notes": list(p.notes), "stages": []}
    budget_main = time_limit_s * 0.85
    built, solver, status = None, None, None

    if len(p.cands) > SINGLE_STAGE_MAX_CANDS and STRATEGY == "greedy":
        tg = time.perf_counter()
        chosen0, roles0 = greedy(p)
        built = Builder(p).build()
        hint = {v: 0 for v in built.y.values()}
        for idx in chosen0:
            if idx in built.y:
                hint[built.y[idx]] = 1
        for (eid, r, a), v in built.x.items():
            hint[v] = int(roles0.get((eid, a)) == r)
        stats["stages"].append({"stage": "greedy", "shifts": len(chosen0), "s": round(time.perf_counter() - tg, 2)})
        solver, status = solve(built, max(1.0, budget_main - (time.perf_counter() - t0)), hint=hint)
    elif len(p.cands) > SINGLE_STAGE_MAX_CANDS and STRATEGY == "coarse":
        for ss, ls in COARSE_STEPS:
            ok = _coarse_filter(p, ss, ls)
            n = sum(1 for c in p.cands if ok(c))
            if n <= COARSE_MAX_CANDS or (ss, ls) == COARSE_STEPS[-1]:
                break
        bA = Builder(p, cand_ok=ok).build()
        tA = max(1.0, budget_main * 0.5 - (time.perf_counter() - t0))
        sA, stA = solve(bA, tA)
        stats["stages"].append({"stage": "coarse", "steps": [ss, ls], "cands": len(bA.y),
                                "status": sA.status_name(stA), "s": round(sA.wall_time, 2),
                                **({"obj": round(sA.objective_value / SCALE, 2)} if stA in STATUS and stA != cp_model.INFEASIBLE else {})})
        bB = Builder(p).build()
        hint = _hint_from(bA, sA, bB) if stA in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
        tB = max(1.0, (t0 + budget_main) - time.perf_counter())
        sB, stB = solve(bB, tB, hint=hint)
        stats["stages"].append({"stage": "full", "cands": len(bB.y), "status": sB.status_name(stB),
                                "s": round(sB.wall_time, 2), "hinted": hint is not None})
        built, solver, status = bB, sB, stB
        if stB not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE) and stA in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            built, solver, status = bA, sA, cp_model.FEASIBLE  # full grid found nothing in time: use A
    else:
        built = Builder(p).build()
        solver, status = solve(built, max(1.0, budget_main - (time.perf_counter() - t0)))
    stats.update({"solver_status": solver.status_name(status), "num_role_vars": len(built.x),
                  "build_and_solve_s": round(time.perf_counter() - t0, 3)})
    if status == cp_model.INFEASIBLE:
        inf = find_conflicts(config, time_limit_s=max(5.0, time_limit_s / 2))
        if inf is None:
            inf = Infeasibility(summary="The solver proved the hard rules cannot all hold, but could not "
                                        "isolate which ones within the time limit.")
        return _base(config, "infeasible", infeasibility=inf, solver_stats=stats)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        stats["error"] = "No schedule found within the time limit."
        return _base(config, "error", solver_stats=stats)

    # Phase 2: keep the chosen shifts, re-assign roles with a small churn tiebreak so
    # people don't flicker between roles. Coverage/soft terms stay in the objective.
    chosen = {c.idx for c in p.cands if c.idx in built.y and solver.boolean_value(built.y[c.idx])}
    obj1, bound1 = solver.objective_value, solver.best_objective_bound
    b2 = Builder(p, cand_ok=lambda c: c.idx in chosen, churn=True, force_cands=True).build()
    s2, st2 = solve(b2, min(5.0, max(0.5, deadline - time.perf_counter())))
    if st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        built, solver = b2, s2
        stats["phase2_status"] = s2.status_name(st2)
    shifts = shifts_from_solution(built, solver)
    soft = soft_from_solution(built, solver) + availability_violations(p, shifts)
    gaps = gaps_from_shifts(p, shifts)
    sched = _base(config, STATUS[status], shifts=shifts, soft_violations=soft)
    for g in gaps:
        g.reasons = explain_with_prep(p, sched, g)
    sched.gaps = gaps
    sched.metrics = compute_metrics(p, shifts, soft, gaps)
    obj = obj1 + built.objective_const_units
    bound = bound1 + built.objective_const_units
    stats.update({
        "phase1_objective_dollars": round(obj / SCALE, 2),
        "best_bound_dollars": round(bound / SCALE, 2),
        "relative_gap": round((obj - bound) / obj, 6) if obj else 0.0,
        "total_s": round(time.perf_counter() - t0, 3),
    })
    sched.solver_stats = stats
    return sched


def find_conflicts(config: StoreConfig, time_limit_s: float = 10) -> Optional[Infeasibility]:
    """Hard-only feasibility check. None if the hard rules can all hold."""
    p = build_prep(config, prune=False)
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
