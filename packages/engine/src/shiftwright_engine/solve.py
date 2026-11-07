"""solve_week and find_conflicts."""
from __future__ import annotations

import os
import time
from typing import Optional

from ortools.sat.python import cp_model

from shiftwright_contracts.models import ConstraintKind, Infeasibility, LawRuleType, Schedule, StoreConfig, Strength

from .bounds import always_staffed_conflict
from .explain import explain_with_prep
from .greedy import greedy, repair
from .lex import role_tier
from .tradeoffs import tradeoffs
from .why import annotate
from .model import Builder, day_bounds, default_workers, max_shifts_per_day, solve
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
FULL_MODEL_MAX_CANDS = int(os.environ.get("ENGINE_FULL_MODEL_MAX", "0"))  # above: day-by-day LNS


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


SPLIT_SEED_HOURLY_ABOVE = 20_000


def _seed_always_staffed(p, roles: set[str], time_limit_s: float, stats: dict):
    """Small dedicated model: shifts for the people who may work a hard always_staffed role that
    keep those roles covered, within their hard limits, fewest paid minutes. Used to seed the greedy
    start. Returns (chosen idxs, {(emp, slot): role}) or None."""
    t = time.perf_counter()
    elig = {e for e, rs in p.allowed_roles.items() if roles & set(rs)}
    cands = [c for c in p.cands if c.emp in elig]
    n_max = max_shifts_per_day(p)
    if n_max > 1 and len(cands) > SPLIT_SEED_HOURLY_ABOVE:  # split days are much harder: hourly grid
        lo = {eid: p.shift_bounds(eid)[0] for eid in elig}
        cands = [c for c in cands if c.start % 60 == 0 and (c.end - c.start - lo[c.emp]) % 60 == 0]
    m = cp_model.CpModel()
    y = {c.idx: m.new_bool_var("") for c in cands}
    by_ed: dict = {}
    for c in cands:
        by_ed.setdefault((c.emp, c.day), []).append(c)
    works = {}
    for k, lst in by_ed.items():
        w = m.new_bool_var("")
        if n_max == 1:
            m.add(sum(y[c.idx] for c in lst) == w)
        else:
            m.add(sum(y[c.idx] for c in lst) <= n_max * w)
            m.add(sum(y[c.idx] for c in lst) >= w)
        works[k] = w
    if n_max > 1:  # split days: no overlap (boolean running on-shift sum), one slot between shifts
        starts: dict = {}
        ends: dict = {}
        slots_of: dict = {}
        for c in cands:
            starts.setdefault((c.emp, c.abs_start), []).append(y[c.idx])
            ends.setdefault((c.emp, c.abs_end), []).append(y[c.idx])
            slots_of.setdefault(c.emp, set()).update(c.on_slots)
        for eid, sl in slots_of.items():
            prev = None
            for a in sorted(sl):
                v = m.new_bool_var("")
                before = prev if prev is not None and prev[0] == a - p.slot else None
                m.add(v == (before[1] if before else 0) + sum(starts.get((eid, a), [])) - sum(ends.get((eid, a), [])))
                if before:
                    m.add(sum(starts.get((eid, a), [])) + before[1] <= 1)
                prev = (a, v)
        first_start, last_end = day_bounds(m, y, by_ed)
        no_ot = p.daily_ot is not None and not p.cfg.budget.overtime_allowed
        for (eid, d), lst in by_ed.items():
            caps = [p.minor_day_cap(p.emps[eid], d)] + ([int(p.daily_ot.params["threshold_hours"] * 60)] if no_ot else [])
            caps = [x for x in caps if x is not None]
            if caps and len(lst) > 1:
                m.add(sum(y[c.idx] * c.paid_min for c in lst) <= min(caps))
    rest = 0
    for c in p.constraints:
        if c.kind == ConstraintKind.min_rest_between_shifts:
            rest = max(rest, int(c.params["minutes"]))
    for lr in p.law_of(LawRuleType.min_rest_between_shifts):
        rest = max(rest, int(lr.params["minutes"]))
    for (eid, d), w in works.items():
        nxt = works.get((eid, d + 1))
        if nxt is not None:
            if n_max > 1:
                end_d, start_n = last_end[(eid, d)], first_start[(eid, d + 1)]
            else:
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


COARSE_DAY_LNS_CANDS = 150_000
DAY_LNS_MIN_S = 0.8  # least CP-SAT time worth giving a day model
PLATEAU_DAY_S = 3.0  # per day model when solving to a plateau (no time limit)
# A week counts as better (resets the plateau clock) when open tier-weighted demand drops by this
# share, or, at no less coverage, the guided objective by this share.
PLATEAU_TOL_OPEN, PLATEAU_TOL_COST = 0.002, 0.005
PLATEAU_TRADEOFF_S = 20.0  # what-ifs after a plateau solve, inside max_s
PLATEAU_GAP = 0.01  # CP-SAT stages stop once proven within 1% of their bound
ELASTIC_ALWAYS_DOLLARS_PER_HOUR = 1000.0  # day LNS: hard always_staffed priced, so any start can be improved


def _open_by_day(p, roles: dict) -> dict[int, float]:
    """Uncovered demand per day (headcount-minutes × gap_penalty_per_hour), from slot roles."""
    have: dict[tuple[str, int], int] = {}
    for (_e, a), r in roles.items():
        have[(r, a)] = have.get((r, a), 0) + 1
    pen = role_tier(p)
    out: dict[int, float] = {}
    for (r, a), dem in p.demand.items():
        miss = dem - have.get((r, a), 0)
        if miss > 0 and r in pen:
            out[a // DAY] = out.get(a // DAY, 0) + miss * p.slot * pen[r]
    return out


def _day_lns(p, chosen0: set[int], roles0: dict, until: float, stats: dict,
             plateau_s: Optional[float] = None):
    """Improve the greedy week one day at a time: that day's full candidate grid, every other day's
    shifts fixed, hinted with the current week (y and x). Hard always_staffed is priced at
    $1000/h inside the day models so a start with holes can still be repaired.
    Day models use the guided objective (`model.solve` mode "guide") with an hours allotment per
    day; `greedy.repair` then fills what is still open, coverage first.
    With `plateau_s` (no time limit given), each day model gets `PLATEAU_DAY_S` and rounds go on
    until a full round is done and nothing better (open tier-weighted demand, then the guided
    objective) has been found for `plateau_s`, or `until`; `stats["lns_stop"]` says which.
    Returns (chosen, roles, objective units, always_staffed holes left) or None if no day solved."""
    days = sorted(p.windows)
    st8 = {"cur": set(chosen0), "roles": dict(roles0), "obj": None, "holes": None}
    always_ids = {c.id for c in p.constraints
                  if c.kind == ConstraintKind.always_staffed and c.strength == Strength.hard}
    rounds, solved = 0, 0
    t_start = time.perf_counter()
    coarse = len(p.cands) > COARSE_DAY_LNS_CANDS  # day models on the hourly grid (+ current shifts)
    lo = {eid: p.shift_bounds(eid)[0] for eid in p.emps}

    def on_grid(c) -> bool:
        return not coarse or (c.start % 60 == 0 and (c.end - c.start - lo[c.emp]) % 60 == 0)
    b0 = p.cfg.budget
    cap_min = int(round((b0.weekly_hours_cap + sum(a.extra_hours for a in b0.approvals)) * 60))

    def day_solve(d: int, per: float, rest_days: list[int]) -> bool:
        cur, roles = st8["cur"], st8["roles"]
        paid = {dd: 0 for dd in days}
        for i in cur:
            paid[p.cands[i].day] = paid.get(p.cands[i].day, 0) + p.cands[i].paid_min
        slack = max(0, cap_min - sum(paid.values()))
        # Hours allotment under a binding budget: a day model sees only its share of the week's
        # unused hours, by open demand, so it can't spend them all on its own lowest tier; what it
        # doesn't use rolls on to the next day solved.
        open_ = _open_by_day(p, roles)
        later = sum(open_.get(dd, 0) for dd in rest_days)
        share = slack if later <= 0 else int(slack * open_.get(d, 0) / later)
        forced = {i for i in cur if p.cands[i].day != d}
        def ok(c) -> bool:
            return (c.day == d and on_grid(c)) or c.idx in cur
        b = Builder(p, cand_ok=ok, forced=forced,
                    elastic_always=ELASTIC_ALWAYS_DOLLARS_PER_HOUR if always_ids else 0.0,
                    day_paid_cap=(d, paid.get(d, 0) + share)).build()
        hint = {v: int(i in cur) for i, v in b.y.items()}
        for (e, r, a), v in b.x.items():
            hint[v] = int(roles.get((e, a)) == r)
        s, st = solve(b, per, hint=hint, mode="guide")
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return False
        st8["cur"] = {i for i, v in b.y.items() if s.boolean_value(v)}
        st8["roles"] = {(e, a): r for (e, r, a), v in b.x.items() if s.boolean_value(v)}
        st8["obj"] = s.objective_value
        st8["holes"] = sum(s.value(t.var) for t in b.soft if t.constraint_id in always_ids)
        return True

    best = [None, time.perf_counter()]  # best (open, obj) key, when it was found

    def improved() -> None:
        key = (sum(_open_by_day(p, st8["roles"]).values()), st8["obj"])
        b = best[0]
        if b is None or key[0] < b[0] * (1 - PLATEAU_TOL_OPEN) or (
                key[0] <= b[0] and key[1] < b[1] - abs(b[1]) * PLATEAU_TOL_COST):
            best[0], best[1] = key, time.perf_counter()

    def done(reason: Optional[str]):
        if reason:
            stats["lns_stop"] = reason
        stats["stages"].append({"stage": "day_lns", "rounds": rounds, "day_solves": solved,
                                "s": round(time.perf_counter() - t_start, 2), "holes": st8["holes"]})
        if st8["obj"] is None:
            return None
        return st8["cur"], st8["roles"], st8["obj"], st8["holes"]

    while True:
        order = days
        fit = int((until - time.perf_counter()) // (DAY_LNS_MIN_S + 1.0))
        if 0 < fit < len(days):  # short limit / slow machine: the days with the most open demand first
            open_ = _open_by_day(p, st8["roles"])
            order = sorted(sorted(days, key=lambda dd: -open_.get(dd, 0))[:fit])
        for k, d in enumerate(order):
            if plateau_s is not None:
                if rounds and time.perf_counter() - best[1] >= plateau_s:
                    return done("plateau")
                per = min(PLATEAU_DAY_S, until - time.perf_counter() - 1.0)
                if per < DAY_LNS_MIN_S:
                    return done("cap")
            else:
                per = (until - time.perf_counter()) / max(1, len(order) - k) - 1.0  # ~1 s to build a day model
                if per < DAY_LNS_MIN_S:
                    return done(None)
            if day_solve(d, per, order[k:]):
                solved += 1
                improved()
        rounds += 1




def solve_week(config: StoreConfig, time_limit_s: Optional[float] = 20, previous: Optional[Schedule] = None,
               plateau_s: float = 8.0, max_s: float = 90.0) -> Schedule:
    """`time_limit_s=None`: stop when it stops improving instead of on a clock: CP-SAT stages stop
    within 1% of their bound, day LNS after `plateau_s` without a better week (after one full
    round), all inside `max_s` including the tradeoff what-ifs. `solver_stats.stop_reason` is
    "proven_close" | "plateau" | "cap" | "time_limit".
Large models start CP-SAT from a greedy schedule (seeded with a small always_staffed model).
    Phase 2 re-assigns roles with the churn tiebreak on the chosen shifts. A proven-infeasible
    result is reported only when CP-SAT or the always_staffed bound proves it; if CP-SAT finds
    nothing in time, the greedy schedule is checked against the full model and returned as
    "feasible" when it holds."""
    t0 = time.perf_counter()
    plateau = time_limit_s is None
    if plateau:
        time_limit_s = max(5.0, max_s - PLATEAU_TRADEOFF_S)
    gap = PLATEAU_GAP if plateau else None
    deadline = t0 + time_limit_s
    reserve = min(6.5, max(1.0, time_limit_s * 0.22))  # repair / phase 2 rounds + output
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
        lns = _day_lns(p, chosen0, roles0, deadline - reserve, stats, plateau_s=plateau_s if plateau else None)
        if lns is not None and lns[3]:  # always_staffed holes left: hand the week to the hard model
            chosen0, roles0 = lns[0], lns[1]
            lns = None
    roles_now: dict = {}
    if lns is not None:
        chosen, roles_now, obj1, _ = lns
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
        solver, status = solve(built, left(1.0), hint=hint, gap=gap)
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
            roles_now = {(e, a): r for (e, r, a), v in built.x.items() if solver.boolean_value(v)}
            obj1, bound1 = solver.objective_value, solver.best_objective_bound
        elif chosen0 or len(p.cands) <= SINGLE_STAGE_MAX_CANDS:
            if chosen0 is None:  # small model timed out (e.g. a loaded machine): greedy start as fallback
                chosen0, roles0 = greedy(p)
            chosen, obj1, bound1 = chosen0, None, solver.best_objective_bound
            roles_now = dict(roles0)
            stats["fallback"] = "greedy"
        else:
            stats["error"] = "No schedule found within the time limit."
            return _base(config, "error", solver_stats=stats)
        del built, solver, hint  # free the phase-1 model before phase 2
    sched_status = STATUS.get(status, "feasible")

    # Coverage-first finishing, then phase 2: fill demand still open with legal extensions / short
    # shifts (`repair`), then keep the chosen shifts and re-assign roles (coverage first, then cost
    # with a small churn tiebreak so people don't flicker between roles). Phase 2 also re-checks
    # every hard rule on the repaired week; if that fails, the week before the repair is kept.
    # Phase 2's roles open new repairs, so this repeats while time allows.
    good = None
    for _round in range(6):
        tr = time.perf_counter()
        repaired, _, moves = repair(p, chosen, roles_now)
        stats["stages"].append({"stage": "repair", "moves": moves, "s": round(time.perf_counter() - tr, 2)})
        if good is not None and not moves:
            break
        tries = ([repaired] if moves else []) + ([chosen] if good is None else [])
        for keep in tries:
            b2 = Builder(p, cand_ok=lambda c, keep=keep: c.idx in keep, churn=True, force_cands=True).build()
            p2_limit = max(1.0, deadline - time.perf_counter() - 1.5)
            s2, st2 = solve(b2, min(p2_limit, 15.0) if plateau else p2_limit, mode="lex", gap=gap)
            if st2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE) and st2 != cp_model.INFEASIBLE:
                b2 = Builder(p, cand_ok=lambda c, keep=keep: c.idx in keep, force_cands=True).build()  # retry without churn
                s2, st2 = solve(b2, 2.0, mode="lex")
            if st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                good = (b2, s2, keep)
                stats["phase2_status"] = s2.status_name(st2)
                break
            stats["repair_dropped"] = s2.status_name(st2)
        else:
            if good is None:
                stats["error"] = "No schedule found within the time limit."
                return _base(config, "error", solver_stats=stats)
            break
        b2, s2, chosen = good
        roles_now = {(e, a): r for (e, r, a), v in b2.x.items() if s2.boolean_value(v)}
        if deadline - time.perf_counter() < (time.perf_counter() - tr) + 1.0:
            break
    built, solver, chosen = good
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
    if not plateau:
        stats["stop_reason"] = "time_limit"
    elif "lns_stop" in stats:
        stats["stop_reason"] = stats["lns_stop"]
    elif stats.get("solver_status") == "OPTIMAL" or (
            stats.get("relative_gap") is not None and stats["relative_gap"] <= PLATEAU_GAP):
        stats["stop_reason"] = "proven_close"
    else:
        stats["stop_reason"] = "cap"
    stats["mode"] = "plateau" if plateau else "time_limit"
    stats["main_s"] = stats["total_s"]
    sched.solver_stats = stats
    # Tradeoffs for the manager (SEMANTICS #25): short what-if solves after the main solve.
    if os.environ.get("ENGINE_TRADEOFFS", "1") != "0":
        main_s = time.perf_counter() - t0
        if not plateau and main_s >= time_limit_s:
            stats["tradeoffs"] = []
            stats["notes"].append("Tradeoffs skipped: the main solve used its whole time limit.")
        else:
            tt = time.perf_counter()
            roles_final = {(e, a): r for (e, r, a), v in built.x.items() if solver.boolean_value(v)}
            if plateau:
                lim, until = 4.0, min(tt + PLATEAU_TRADEOFF_S, t0 + max_s - 1.0)
            else:
                lim, until = min(5.0, max(1.0, time_limit_s * 0.1)), tt + time_limit_s * 0.5
            stats["tradeoffs"] = tradeoffs(p, sched, chosen, roles_final, limit_s=lim, until=until)
            stats["tradeoffs_s"] = round(time.perf_counter() - tt, 2)
    stats["wall_s"] = round(time.perf_counter() - t0, 3)
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
