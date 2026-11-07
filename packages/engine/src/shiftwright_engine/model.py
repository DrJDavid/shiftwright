"""CP-SAT model for one week (or a restricted part of it, for the fixer)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from ortools.sat.python import cp_model

from shiftwright_contracts.models import ConstraintKind, LawRuleType, Strength

from .prep import DAY, SCALE, Prep, _avail_for_day, money

CHURN_DOLLARS = 0.50  # tiebreak per role segment so roles don't flicker


@dataclass
class SoftTerm:
    var: cp_model.IntVar | cp_model.LinearExpr
    units_per: int  # objective units per unit of var
    amount_per: float  # reported amount (hours / occurrences) per unit of var
    constraint_id: Optional[str]
    kind: str
    employee_id: Optional[str]
    note: str = ""
    dollars_per: Optional[float] = None  # exact $ per unit for reporting (else units_per / SCALE)


@dataclass
class Built:
    model: cp_model.CpModel
    prep: Prep
    y: dict[int, cp_model.IntVar]
    x: dict[tuple[str, str, int], cp_model.IntVar]
    gap: dict[tuple[str, int], cp_model.IntVar]
    works: dict[tuple[str, int], cp_model.IntVar]
    weekly_ot: dict[str, cp_model.IntVar]
    soft: list[SoftTerm]
    assumptions: dict[cp_model.IntVar, tuple[str, str]] = field(default_factory=dict)  # lit -> (bucket, id)
    objective_const_units: int = 0


class Builder:
    """Builds the model. With `assume=True`, every hard rule gets an assumption literal and
    the objective is dropped (used by find_conflicts)."""

    def __init__(self, prep: Prep, assume: bool = False,
                 cand_ok: Optional[Callable[[object], bool]] = None,
                 churn: bool = False, force_cands: bool = False):
        self.p = prep
        self.assume = assume
        self.churn = churn
        self.force_cands = force_cands  # every allowed candidate MUST be worked (phase 2 / fixer)
        self.m = cp_model.CpModel()
        self.lits: dict[tuple[str, str], cp_model.IntVar] = {}
        self.cand_ok = cand_ok
        self._zero = self.m.new_constant(0)

    # --- assumption literals -------------------------------------------------
    def guard(self, bucket: str, ident: str) -> list:
        """bucket in {'constraint','law','other'}."""
        if not self.assume:
            return []
        key = (bucket, ident)
        if key not in self.lits:
            self.lits[key] = self.m.new_bool_var(f"A[{bucket}:{ident}]")
        return [self.lits[key]]

    def add(self, ct_expr, enforce: list):
        c = self.m.add(ct_expr)
        if enforce:
            c.only_enforce_if(enforce)
        return c

    # --- build -----------------------------------------------------------------
    def build(self) -> Built:
        p, m = self.p, self.m
        slot = p.slot
        slot_h = slot / 60

        y = {}
        for c in p.cands:
            if self.cand_ok is not None and not self.cand_ok(c):
                continue
            y[c.idx] = m.new_bool_var(f"y{c.idx}")
        cands = [c for c in p.cands if c.idx in y]
        if self.force_cands:
            for c in cands:
                m.add(y[c.idx] == 1)

        # one shift per employee-day; works[e,d]
        works = {}
        by_ed: dict[tuple[str, int], list] = {}
        for c in cands:
            by_ed.setdefault((c.emp, c.day), []).append(c)
        for (eid, d), lst in by_ed.items():
            w = m.new_bool_var(f"w[{eid},{d}]")
            m.add(sum(y[c.idx] for c in lst) == w)
            works[(eid, d)] = w

        # working / on-shift expressions per (e, abs slot)
        # on[e,a] is defined by a running sum (shifts starting at a minus shifts ending at a) instead
        # of summing every candidate that covers a: each y appears in 2 rows, not one per slot.
        starts: dict[tuple[str, int], list] = {}
        ends: dict[tuple[str, int], list] = {}
        on_break: dict[tuple[str, int], list] = {}
        slots_of: dict[str, set[int]] = {}
        working_slots: set[tuple[str, int]] = set()
        for c in cands:
            starts.setdefault((c.emp, c.abs_start), []).append(y[c.idx])
            ends.setdefault((c.emp, c.abs_end), []).append(y[c.idx])
            slots_of.setdefault(c.emp, set()).update(c.on_slots)
            working_slots.update((c.emp, a) for a in c.work_slots)
            ws = set(c.work_slots)
            for a in c.on_slots:
                if a not in ws:
                    on_break.setdefault((c.emp, a), []).append(y[c.idx])
        onshift: dict[tuple[str, int], cp_model.IntVar] = {}
        working: dict[tuple[str, int], object] = {}
        for eid, sl in slots_of.items():
            for a in sorted(sl):
                v = m.new_bool_var(f"on[{eid},{a}]")
                prev = onshift.get((eid, a - slot))
                m.add(v == (prev if prev is not None else 0) + sum(starts.get((eid, a), []))
                      - sum(ends.get((eid, a), [])))
                onshift[(eid, a)] = v
                if (eid, a) in working_slots:
                    working[(eid, a)] = v - sum(on_break.get((eid, a), [])) if (eid, a) in on_break else v

        # role assignment
        x = {}
        churn_terms = []
        for (eid, a), wexpr in working.items():
            rs = p.allowed_roles[eid]
            vs = []
            for r in rs:
                v = m.new_bool_var(f"x[{eid},{r},{a}]")
                x[(eid, r, a)] = v
                vs.append(v)
            m.add(sum(vs) == wexpr)
        if self.churn and CHURN_DOLLARS > 0:
            for (eid, r, a), v in x.items():
                prev = x.get((eid, r, a - slot))
                if prev is None:
                    churn_terms.append(v)
                else:
                    s = m.new_bool_var("")
                    m.add(s >= v - prev)
                    churn_terms.append(s)

        # coverage & gaps
        cov: dict[tuple[str, int], list] = {}
        for (eid, r, a), v in x.items():
            cov.setdefault((r, a), []).append(v)
        gap = {}
        gap_terms = []
        roles = {r.id: r for r in p.cfg.roles}
        for (r, a), dem in p.demand.items():
            g = m.new_int_var(0, dem, f"gap[{r},{a}]")
            m.add(g + sum(cov.get((r, a), [])) >= dem)
            gap[(r, a)] = g
            pen = roles[r].gap_penalty_per_hour if r in roles else 0.0
            gap_terms.append((g, money(pen * slot_h)))

        soft: list[SoftTerm] = []
        const_units = 0

        # --- per-employee hard rules --------------------------------------------
        weekly_ot = {}
        paid_by_emp: dict[str, list] = {}
        for c in cands:
            paid_by_emp.setdefault(c.emp, []).append((y[c.idx], c.paid_min, c.daily_ot_min))
        for eid, terms in paid_by_emp.items():
            e = p.emps[eid]
            total = sum(v * m_ for v, m_, _ in terms)
            for cap, bucket, ident in p.effective_max_minutes(e):
                g = self.guard("other" if bucket == "employee" else "law", ident)
                if g:  # filtering already enforces it without assumptions; keep it explicit here
                    self.add(total <= cap, g)
                else:
                    m.add(total <= cap)
            if p.weekly_ot is not None and p.cfg.budget.overtime_allowed:
                thr = int(p.weekly_ot.params["threshold_hours"] * 60)
                ot = m.new_int_var(0, 7 * DAY, f"ot[{eid}]")
                m.add(ot >= total - sum(v * d_ for v, _, d_ in terms) - thr)
                weekly_ot[eid] = ot

        # --- rest between shifts (always no overlap; plus rules) ------------------
        rest_rules = []  # (minutes, bucket, id, strength, weight, applies)
        for c in p.constraints:
            if c.kind == ConstraintKind.min_rest_between_shifts:
                rest_rules.append((int(c.params["minutes"]), "constraint", c.id, c.strength, c.weight_dollars, c))
        for lr in p.law_of(LawRuleType.min_rest_between_shifts):
            # Engine policy: law rest rules are honored as hard bans (never pay the premium).
            rest_rules.append((int(lr.params["minutes"]), "law", lr.id, Strength.hard, 0.0, None))
        for (eid, d), w in works.items():
            nxt = works.get((eid, d + 1))
            if nxt is None:
                continue
            end_d = sum(y[c.idx] * c.abs_end for c in by_ed[(eid, d)])
            start_n = sum(y[c.idx] * c.abs_start for c in by_ed[(eid, d + 1)])
            m.add(start_n - end_d >= 0).only_enforce_if([w, nxt])
            for minutes, bucket, ident, strength, weight, con in rest_rules:
                if con is not None and not p.applies(con, eid):
                    continue
                if strength == Strength.hard:
                    m.add(start_n - end_d >= minutes).only_enforce_if([w, nxt] + self.guard(bucket, ident))
                elif not self.assume:
                    miss = m.new_int_var(0, minutes, "")  # minutes of rest missing ($/hour missing)
                    m.add(start_n - end_d + miss >= minutes).only_enforce_if([w, nxt])
                    soft.append(SoftTerm(miss, money(weight / 60), 1 / 60, ident, con.kind.value, eid,
                                         dollars_per=weight / 60))

        days = sorted(p.windows)
        for con in p.constraints:
            k, hard = con.kind, con.strength == Strength.hard
            if not hard and self.assume:
                continue
            g = self.guard("constraint", con.id) if hard else []
            emps = [e.id for e in p.cfg.employees if p.applies(con, e.id)]
            if k == ConstraintKind.max_days_per_week:
                lim = int(con.params["days"])
                for eid in emps:
                    ws = [works[(eid, d)] for d in days if (eid, d) in works]
                    if not ws:
                        continue
                    if hard:
                        self.add(sum(ws) <= lim, g)
                    else:
                        ex = m.new_int_var(0, 7, "")
                        m.add(ex >= sum(ws) - lim)
                        soft.append(SoftTerm(ex, money(con.weight_dollars), 1.0, con.id, k.value, eid))
            elif k == ConstraintKind.max_consecutive_days:
                lim = int(con.params["days"])
                for eid in emps:
                    for d0 in range(0, 7 - lim):
                        ws = [works[(eid, d)] for d in range(d0, d0 + lim + 1) if (eid, d) in works]
                        if len(ws) <= lim:
                            continue
                        if hard:
                            self.add(sum(ws) <= lim, g)
                        else:
                            ex = m.new_int_var(0, 7, "")
                            m.add(ex >= sum(ws) - lim)
                            soft.append(SoftTerm(ex, money(con.weight_dollars), 1.0, con.id, k.value, eid))
            elif k == ConstraintKind.min_hours_week:
                for eid in emps:
                    e = p.emps[eid]
                    need = int(round(e.min_hours_week * 60))
                    if need <= 0:
                        continue
                    total = sum(v * mm for v, mm, _ in paid_by_emp.get(eid, [])) + self._zero
                    if hard:
                        self.add(total >= need, g)
                    else:
                        short = m.new_int_var(0, need, "")
                        m.add(short >= need - total)
                        # units per minute short
                        soft.append(SoftTerm(short, max(1, money(con.weight_dollars) // 60), 1 / 60,
                                             con.id, k.value, eid))
            elif k == ConstraintKind.not_together:
                ids = list(con.params.get("employee_ids", []))
                if len(ids) != 2:
                    continue
                ea, eb = ids
                for a_slot in {a for (e_, a) in onshift if e_ == ea} & {a for (e_, a) in onshift if e_ == eb}:
                    sa, sb = onshift[(ea, a_slot)], onshift[(eb, a_slot)]
                    if hard:
                        self.add(sa + sb <= 1, g)
                    else:
                        ov = m.new_bool_var("")
                        m.add(ov >= sa + sb - 1)
                        soft.append(SoftTerm(ov, money(con.weight_dollars * slot_h), slot_h, con.id, k.value, None))
            elif k == ConstraintKind.fair_spread:
                cls = con.params.get("shift_class")
                lim = int(con.params.get("max_per_employee", 0))
                attr = {"open": "is_open", "close": "is_close", "weekend": "weekend"}.get(cls)
                if attr is None:
                    continue
                for eid in emps:
                    vs = [y[c.idx] for c in cands if c.emp == eid and getattr(c, attr)]
                    if len(vs) <= lim:
                        continue
                    if hard:
                        self.add(sum(vs) <= lim, g)
                    else:
                        ex = m.new_int_var(0, 7, "")
                        m.add(ex >= sum(vs) - lim)
                        soft.append(SoftTerm(ex, money(con.weight_dollars), 1.0, con.id, k.value, eid))
            elif k == ConstraintKind.always_staffed:
                rid = con.params.get("role_id")
                which = con.params.get("windows", "store_hours")
                for d in days:
                    lo, hi = p.store_open[d] if which == "store_hours" else p.windows[d]
                    t = lo - lo % p.slot
                    while t < hi:
                        a = d * DAY + t
                        terms = cov.get((rid, a), [])
                        if hard:
                            self.add(sum(terms) + self._zero >= 1, g)
                        else:
                            unc = m.new_bool_var("")
                            m.add(sum(terms) + unc >= 1)
                            soft.append(SoftTerm(unc, money(con.weight_dollars * slot_h), slot_h, con.id, k.value,
                                                 None, dollars_per=con.weight_dollars * slot_h))
                        t += p.slot
            elif k == ConstraintKind.preferred_role:
                eid, rid = con.params.get("employee_id"), con.params.get("role_id")
                if eid not in p.emps or rid not in p.allowed_roles.get(eid, []):
                    continue
                for (e_, r_, a), v in x.items():
                    if e_ != eid or r_ == rid:
                        continue
                    if hard:
                        self.add(v == 0, g)
                    else:
                        soft.append(SoftTerm(v, money(con.weight_dollars * slot_h), slot_h, con.id, k.value, eid))
            # min/max_shift_length: applied in candidate generation (hard only).
            # week_stability: not yet modeled (see STATUS.md).

        # --- soft shift length ($/hour short or over), per candidate ----------------
        if not self.assume:
            for con in p.constraints:
                if con.strength != Strength.soft or con.kind not in (ConstraintKind.min_shift_length,
                                                                     ConstraintKind.max_shift_length):
                    continue
                lim = int(con.params["minutes"])
                for c in cands:
                    if not p.applies(con, c.emp):
                        continue
                    length = c.end - c.start
                    dev = (lim - length) if con.kind == ConstraintKind.min_shift_length else (length - lim)
                    if dev > 0:
                        h = dev / 60
                        soft.append(SoftTerm(y[c.idx], money(con.weight_dollars * h), h, con.id, con.kind.value,
                                             c.emp, dollars_per=con.weight_dollars * h))

        # --- budget -----------------------------------------------------------------
        b = p.cfg.budget
        cap_h = b.weekly_hours_cap + sum(a.extra_hours for a in b.approvals)
        all_paid = sum(y[c.idx] * c.paid_min for c in cands) + self._zero
        self.add(all_paid <= int(round(cap_h * 60)), self.guard("other", "budget.weekly_hours_cap"))
        wage_expr = sum(y[c.idx] * c.wage_units for c in cands) + self._zero
        ot_expr = 0
        if weekly_ot:
            mult = p.weekly_ot.params["multiplier"]
            ot_expr = sum(v * money(p.emps[eid].wage_per_hour * (mult - 1) / 60) for eid, v in weekly_ot.items())
        if b.weekly_dollar_cap is not None:
            cap_d = b.weekly_dollar_cap + sum(a.extra_dollars for a in b.approvals)
            self.add(wage_expr + ot_expr <= money(cap_d), self.guard("other", "budget.weekly_dollar_cap"))

        # --- objective ----------------------------------------------------------------
        if not self.assume:
            pref = sum(y[c.idx] * c.pref_units for c in cands if c.pref_units) if cands else 0
            # preferred_on: constant penalty for the full window, minus overlap (already in pref_units)
            for e in p.cfg.employees:
                for d in days:
                    for a in _avail_for_day(p, e, d):
                        if a.kind.value == "preferred_on":
                            const_units += money(a.weight_dollars * (a.end - a.start) / 60)
            obj = (wage_expr + ot_expr + pref
                   + sum(g * u for g, u in gap_terms)
                   + sum(s.var * s.units_per for s in soft)
                   + money(CHURN_DOLLARS) * sum(churn_terms))
            m.minimize(obj)

        built = Built(model=m, prep=p, y=y, x=x, gap=gap, works=works, weekly_ot=weekly_ot, soft=soft,
                      objective_const_units=const_units)
        built.assumptions = {lit: key for key, lit in self.lits.items()}
        if self.assume:
            m.add_assumptions(list(self.lits.values()))
        return built


def default_workers() -> int:
    """CP-SAT workers: env ENGINE_WORKERS, else min(8, cpu count). Memory grows with workers."""
    env = os.environ.get("ENGINE_WORKERS", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return min(8, os.cpu_count() or 1)


def solve(built: Built, time_limit_s: float, workers: Optional[int] = None, hint: Optional[dict] = None,
          light_presolve: bool = True):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_workers = workers or default_workers()
    solver.parameters.log_search_progress = os.environ.get("ENGINE_LOG") == "1"
    if light_presolve:  # full presolve costs ~15 s on the demo store and barely shrinks it
        solver.parameters.max_presolve_iterations = 1
        solver.parameters.cp_model_probing_level = 0
        solver.parameters.symmetry_level = 0
    if hint:
        for v, val in hint.items():
            built.model.add_hint(v, val)
    status = solver.solve(built.model)
    return solver, status


__all__ = ["Builder", "Built", "SoftTerm", "solve", "SCALE"]
