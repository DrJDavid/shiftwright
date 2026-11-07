"""solve_week and find_conflicts."""
from __future__ import annotations

import time
from typing import Optional

from ortools.sat.python import cp_model

from shiftwright_contracts.models import ConstraintKind, Infeasibility, LawRuleType, Schedule, StoreConfig, Strength

from .bounds import always_staffed_conflict
from .explain import explain_with_prep
from .greedy import greedy
from .why import annotate
from .model import Builder, default_workers, solve
from .output import (
    availability_violations,
    compute_metrics,
    gaps_from_shifts,
    shifts_from_solution,
    soft_from_solution,
)
from .prep import DAY, SCALE, build_prep

STATUS = {cp_model.OPTIMAL: "optimal", cp_model.FEASIBLE: "feasible", cp_model.INFEASIBLE: "infeasible"}


def _base(config: StoreConfig, status: str, **kw) -> Schedule:
    return Schedule(store_id=config.store.id, week_start=config.store.week_start,
                    config_version=config.config_version, produced_by="engine", status=status, **kw)


SINGLE_STAGE_MAX_CANDS = 8_000  # above this, start CP-SAT from a greedy schedule
FULL_MODEL_MAX_CANDS = 100_000  # above this, CP-SAT gets the hourly grid plus the greedy shifts only


def _hard_always_roles(p) -> set[str]:
    return {c.params.get("role_id") for c in p.constraints
            if c.kind == ConstraintKind.always_staffed and c.strength == Strength.hard}


def _always_covered(p, chosen: set[int], roles_at: dict) -> bool:
    """Every hard always_staffed slot and sub-interval is worked (breaks excluded, SEMANTICS #18)."""
    nsub = len(p.sub_bounds())
    staffed = set()
    for idx in chosen:
        c = p.cands[idx]
        for a in c.work_slots:
            r = roles_at.get((c.emp, a))
            brk = c.part.get(a, 0)
            staffed.update((r, a, k) for k in range(nsub) if not brk >> k & 1)
    for con in p.constraints:
        if con.kind == ConstraintKind.always_staffed and con.strength == Strength.hard:
            rid = con.params.get("role_id")
            which = con.params.get("windows", "store_hours")
            for d, (lo, hi) in (p.store_open if which == "store_hours" else p.windows).items():
                for t in range(lo - lo % p.slot, hi, p.slot):
                    if any((rid, d * DAY + t, k) not in staffed for k in range(nsub)):
                        return False
    return True


def _seed_always_staffed(p, roles: set[str], time_limit_s: float, stats: dict):
    """Small dedicated model: shifts for the people who may work a hard always_staffed role that
    keep those roles covered, within their hard limits, fewest paid minutes. Used to seed the greedy
    start. Returns (chosen idxs, {(emp, slot): role}) or None."""
    t = time.perf_counter()
    elig = {e for e, rs in p.allowed_roles.items() if roles & set(rs)}
    cands = [c for c in p.cands if c.emp in elig]
    m = cp_model.CpModel()
    y = {c.idx: m.new_bool_var("") for c in cands}
    by_ed: dict = {}
    for c in cands:
        by_ed.setdefault((c.emp, c.day), []).append(c)
    works = {}
    for k, lst in by_ed.items():
        w = m.new_bool_var("")
        m.add(sum(y[c.idx] for c in lst) == w)
        works[k] = w
    rest = 0
    for c in p.constraints:
        if c.kind == ConstraintKind.min_rest_between_shifts:
            rest = max(rest, int(c.params["minutes"]))
    for lr in p.law_of(LawRuleType.min_rest_between_shifts):
        rest = max(rest, int(lr.params["minutes"]))
    for (eid, d), w in works.items():
        nxt = works.get((eid, d + 1))
        if nxt is not None:
            end_d = sum(y[c.idx] * c.abs_end for c in by_ed[(eid, d)])
            start_n = sum(y[c.idx] * c.abs_start for c in by_ed[(eid, d + 1)])
            m.add(start_n - end_d >= rest).only_enforce_if([w, nxt])
    for eid in elig:
        ys = [(y[c.idx], c.paid_min) for c in cands if c.emp == eid]
        if not ys:
            continue
        m.add(sum(v * pm for v, pm in ys) <= min(cap for cap, _, _ in p.effective_max_minutes(p.emps[eid])))
        for con in p.constraints:
            if con.kind == ConstraintKind.max_days_per_week and con.strength == Strength.hard and p.applies(con, eid):
                m.add(sum(w for (e, _), w in works.items() if e == eid) <= int(con.params["days"]))
    cover: dict = {}
    nsub = len(p.sub_bounds())
    for c in cands:
        for a in c.work_slots:
            brk = c.part.get(a, 0)
            for r in roles & set(p.allowed_roles[c.emp]):
                for k in range(nsub):
                    if not brk >> k & 1:
                        cover.setdefault((r, a, k), []).append(y[c.idx])
    for con in p.constraints:
        if con.kind == ConstraintKind.always_staffed and con.strength == Strength.hard:
            rid = con.params.get("role_id")
            which = con.params.get("windows", "store_hours")
            for d, (lo, hi) in (p.store_open if which == "store_hours" else p.windows).items():
                for tt in range(lo - lo % p.slot, hi, p.slot):
                    for k in range(nsub):
                        m.add(sum(cover.get((rid, d * DAY + tt, k), [])) >= 1)
    m.minimize(sum(y[c.idx] * c.paid_min for c in cands))
    solver, st = None, None
    sv = cp_model.CpSolver()
    sv.parameters.max_time_in_seconds = float(time_limit_s)
    sv.parameters.num_workers = default_workers()
    sv.parameters.stop_after_first_solution = False
    st = sv.solve(m)
    stats["stages"].append({"stage": "always_staffed_seed", "employees": len(elig), "cands": len(cands),
                            "status": sv.status_name(st), "s": round(time.perf_counter() - t, 2)})
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    chosen = {idx for idx, v in y.items() if sv.boolean_value(v)}
    by_idx = {c.idx: c for c in cands}
    roles_at = {}
    for idx in chosen:
        c = by_idx[idx]
        r = sorted(roles & set(p.allowed_roles[c.emp]))[0]
        for a in c.work_slots:
            roles_at[(c.emp, a)] = r
    return chosen, roles_at


def _day_lns(p, chosen0: set[int], roles0: dict, until: float, stats: dict):
    """Large models: improve the greedy week one day at a time (full candidate grid for that day,
    every other day's shifts fixed, hinted with the current week). Returns (chosen, objective units)
    or None if the start can't be kept (the caller then solves the restricted week model)."""
    days = sorted(p.windows)
    cur, roles, obj = set(chosen0), dict(roles0), None
    rounds = 0
    t_start = time.perf_counter()
    while True:
        for k, d in enumerate(days):
            remaining = until - time.perf_counter()
            per = remaining / max(1, len(days) - k) - 1.0  # ~1 s to build a day model
            if per < 0.8:
                stats["stages"].append({"stage": "day_lns", "rounds": rounds, "s": round(time.perf_counter() - t_start, 2)})
                return (cur, obj) if obj is not None or rounds else (cur, obj)
            forced = {i for i in cur if p.cands[i].day != d}
            b = Builder(p, cand_ok=lambda c, d=d: c.day == d or c.idx in cur, forced=forced).build()
            hint = {v: int(i in cur) for i, v in b.y.items()}
            for (e, r, a), v in b.x.items():
                hint[v] = int(roles.get((e, a)) == r)
            s, st = solve(b, per, hint=hint)
            if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                cur = {i for i, v in b.y.items() if s.boolean_value(v)}
                roles = {(e, a): r for (e, r, a), v in b.x.items() if s.boolean_value(v)}
                obj = s.objective_value
            elif obj is None and rounds == 0 and k == 0:
                return None  # the greedy start breaks a hard rule somewhere
        rounds += 1


def solve_week(config: StoreConfig, time_limit_s: float = 20, previous: Optional[Schedule] = None) -> Schedule:
    """Large models start CP-SAT from a greedy schedule (seeded with a small always_staffed model).
    Phase 2 re-assigns roles with the churn tiebreak on the chosen shifts. A proven-infeasible
    result is reported only when CP-SAT or the always_staffed bound proves it; if CP-SAT finds
    nothing in time, the greedy schedule is checked against the full model and returned as
    "feasible" when it holds."""
    t0 = time.perf_counter()
    deadline = t0 + time_limit_s
    reserve = min(5.0, max(1.0, time_limit_s * 0.15))  # phase 2 + output
    p = build_prep(config)
    stats: dict = {"num_candidate_shifts": len(p.cands), "notes": list(p.notes), "stages": []}

    def left(minimum: float = 0.5) -> float:
        return max(minimum, deadline - reserve - time.perf_counter())

    always = _hard_always_roles(p)
    if always:
        tb = time.perf_counter()
        inf = always_staffed_conflict(p)
        stats["stages"].append({"stage": "always_staffed_bound", "s": round(time.perf_counter() - tb, 2),
                                "infeasible": inf is not None})
        if inf is not None:
            return _base(config, "infeasible", infeasibility=inf, solver_stats=stats)

    chosen0: Optional[set[int]] = None
    hint = None
    if len(p.cands) > SINGLE_STAGE_MAX_CANDS:
        tg = time.perf_counter()
        chosen0, roles0 = greedy(p)
        stats["stages"].append({"stage": "greedy", "shifts": len(chosen0), "s": round(time.perf_counter() - tg, 2)})
        if always and not _always_covered(p, chosen0, roles0):
            seed = _seed_always_staffed(p, always, min(left() * 0.3, 8.0), stats)
            if seed is not None:
                tg = time.perf_counter()
                chosen0, roles0 = greedy(p, seed)
                stats["stages"].append({"stage": "greedy_seeded", "shifts": len(chosen0),
                                        "s": round(time.perf_counter() - tg, 2)})
    lns = None
    if chosen0 is not None and len(p.cands) > FULL_MODEL_MAX_CANDS:
        lns = _day_lns(p, chosen0, roles0, deadline - reserve, stats)
    if lns is not None:
        chosen, obj1 = lns
        bound1 = None
        status = cp_model.FEASIBLE
        stats["solver_status"] = "DAY_LNS"
    else:
        cand_ok = None
        if chosen0 is not None and len(p.cands) > FULL_MODEL_MAX_CANDS:
            lo = {eid: p.shift_bounds(eid)[0] for eid in p.emps}
            keep = set(chosen0)
            cand_ok = lambda c: c.idx in keep or (c.start % 60 == 0 and (c.end - c.start - lo[c.emp]) % 60 == 0)  # noqa: E731
        tb = time.perf_counter()
        built = Builder(p, cand_ok=cand_ok).build()
        stats["model_candidate_shifts"] = len(built.y)
        stats["build_s"] = round(time.perf_counter() - tb, 2)
        stats["prep_s"] = round(tb - t0, 2)
        if chosen0 is not None:
            hint = {v: 0 for v in built.y.values()}
            for idx in chosen0:
                if idx in built.y:
                    hint[built.y[idx]] = 1
            for (eid, r, a), v in built.x.items():
                hint[v] = int(roles0.get((eid, a)) == r)
        stats["phase1_limit_s"] = round(left(1.0), 2)
        solver, status = solve(built, left(1.0), hint=hint)
        stats.update({"solver_status": solver.status_name(status), "num_role_vars": len(built.x),
                      "build_and_solve_s": round(time.perf_counter() - t0, 3)})
        if status == cp_model.INFEASIBLE:
            inf = find_conflicts(config, time_limit_s=max(1.0, deadline - time.perf_counter()))
            if inf is None or "solver_timeout" in inf.conflicting_other:
                inf = Infeasibility(conflicting_other=["unisolated"],
                                    summary="The solver proved the hard rules cannot all hold, but could not "
                                            "isolate which ones within the time limit.")
            return _base(config, "infeasible", infeasibility=inf, solver_stats=stats)

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            chosen = {c.idx for c in p.cands if c.idx in built.y and solver.boolean_value(built.y[c.idx])}
            obj1, bound1 = solver.objective_value, solver.best_objective_bound
        elif chosen0:
            chosen, obj1, bound1 = chosen0, None, solver.best_objective_bound
            stats["fallback"] = "greedy"
        else:
            stats["error"] = "No schedule found within the time limit."
            return _base(config, "error", solver_stats=stats)
        del built, solver, hint  # free the phase-1 model before phase 2
    sched_status = STATUS.get(status, "feasible")

    # Phase 2: keep the chosen shifts, re-assign roles with a small churn tiebreak so
    # people don't flicker between roles. Coverage/soft terms stay in the objective.
    b2 = Builder(p, cand_ok=lambda c: c.idx in chosen, churn=True, force_cands=True).build()
    s2, st2 = solve(b2, max(1.0, deadline - time.perf_counter() - 1.5))
    stats["phase2_status"] = s2.status_name(st2)
    if st2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        b2 = Builder(p, cand_ok=lambda c: c.idx in chosen, force_cands=True).build()  # retry without churn
        s2, st2 = solve(b2, 2.0)
        if st2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            stats["error"] = "No schedule found within the time limit."
            return _base(config, "error", solver_stats=stats)
    built, solver = b2, s2
    if obj1 is None:  # greedy fallback (objective includes the small churn tiebreak)
        obj1 = s2.objective_value
    shifts = annotate(p, shifts_from_solution(built, solver))
    soft = soft_from_solution(built, solver) + availability_violations(p, shifts)
    gaps = gaps_from_shifts(p, shifts)
    sched = _base(config, sched_status, shifts=shifts, soft_violations=soft)
    for g in gaps:
        g.reasons = explain_with_prep(p, sched, g)
    sched.gaps = gaps
    sched.metrics = compute_metrics(p, shifts, soft, gaps)
    obj = obj1 + built.objective_const_units
    bound = None if bound1 is None else bound1 + built.objective_const_units
    stats.update({
        "phase1_objective_dollars": round(obj / SCALE, 2),
        "best_bound_dollars": None if bound is None else round(bound / SCALE, 2),
        "relative_gap": None if bound is None else (round((obj - bound) / obj, 6) if obj else 0.0),
        "total_s": round(time.perf_counter() - t0, 3),
    })
    sched.solver_stats = stats
    return sched


def find_conflicts(config: StoreConfig, time_limit_s: float = 10) -> Optional[Infeasibility]:
    """Hard-only feasibility check. None if the hard rules can all hold."""
    p = build_prep(config, prune=False)
    inf = always_staffed_conflict(p)
    if inf is not None:
        return inf
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
