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
                 churn: bool = False, force_cands: bool = False, forced: Optional[set[int]] = None,
                 fixed_roles: Optional[dict[tuple[str, int], str]] = None, elastic_always: float = 0.0,
                 min_hours_cap_minutes: int = 0, forced_days: Optional[set[tuple[str, int]]] = None,
                 one_shift_days: Optional[set[tuple[str, int]]] = None):
        self.p = prep
        self.assume = assume
        self.churn = churn
        self.force_cands = force_cands  # every allowed candidate MUST be worked (phase 2 / fixer)
        self.m = cp_model.CpModel()
        self.lits: dict[tuple[str, str], cp_model.IntVar] = {}
        self.cand_ok = cand_ok
        self.forced = forced or set()  # these candidates MUST be worked (fixer: frozen shifts)
        self.fixed_roles = fixed_roles or {}  # (emp, abs slot) -> role that may not change (fixer: before now)
        self.elastic_always = elastic_always  # >0: hard always_staffed priced at this $/h instead (fixer)
        self.min_hours_cap_minutes = min_hours_cap_minutes  # budget hours cap is at least this (fixer)
        self.forced_days = forced_days or set()  # (emp, day) that must have one of their candidates (fixer)
        self.one_shift_days = one_shift_days or set()  # (emp, day) limited to one shift (fixer call-ins)
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
        for c in cands:
            if self.force_cands or c.idx in self.forced:
                m.add(y[c.idx] == 1)

        # up to max_shifts_per_day shifts per employee-day (SEMANTICS #23); works[e,d] is "works that day"
        works = {}
        by_ed: dict[tuple[str, int], list] = {}
        for c in cands:
            by_ed.setdefault((c.emp, c.day), []).append(c)
        n_max = max_shifts_per_day(p)
        split = n_max > 1
        for (eid, d), lst in by_ed.items():
            w = m.new_bool_var(f"w[{eid},{d}]")
            n = sum(y[c.idx] for c in lst)
            if not split or (eid, d) in self.one_shift_days:
                m.add(n == w)
            else:
                m.add(n <= n_max * w)
                m.add(n >= w)
            works[(eid, d)] = w
            if (eid, d) in self.forced_days:
                m.add(w == 1)

        # working / on-shift expressions per (e, abs slot)
        # on[e,a] is defined by a running sum (shifts starting at a minus shifts ending at a) instead
        # of summing every candidate that covers a: each y appears in 2 rows, not one per slot.
        starts: dict[tuple[str, int], list] = {}
        ends: dict[tuple[str, int], list] = {}
        on_break: dict[tuple[str, int], list] = {}
        slots_of: dict[str, set[int]] = {}
        working_slots: set[tuple[str, int]] = set()
        subs = p.sub_bounds()
        part_brk: dict[tuple[str, int, int], list] = {}  # (emp, slot, sub-interval) -> y on break there
        for c in cands:
            starts.setdefault((c.emp, c.abs_start), []).append(y[c.idx])
            ends.setdefault((c.emp, c.abs_end), []).append(y[c.idx])
            slots_of.setdefault(c.emp, set()).update(c.on_slots)
            working_slots.update((c.emp, a) for a in c.work_slots)
            ws = set(c.work_slots)
            for a in c.on_slots:
                if a not in ws:
                    on_break.setdefault((c.emp, a), []).append(y[c.idx])
            for a, mask in c.part.items():
                for k in range(len(subs)):
                    if mask >> k & 1:
                        part_brk.setdefault((c.emp, a, k), []).append(y[c.idx])
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
        if split:
            # on[] is boolean, so an employee's shifts never overlap; also keep at least one slot
            # between two shifts (back-to-back shifts would be one long shift without its breaks).
            for (eid, a), ys in starts.items():
                prev = onshift.get((eid, a - slot))
                if prev is not None:
                    m.add(sum(ys) + prev <= 1)

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
            fr = self.fixed_roles.get((eid, a))
            if fr is not None and (eid, fr, a) in x:
                m.add(x[(eid, fr, a)] == 1)
        # Tipped pay (SEMANTICS #20): wage_units assume the tipped rate; a shift with any untipped
        # role slot pays the full wage, i.e. + untipped_extra_units when nontip[e,d] is on.
        tip_terms = []
        for (eid, d), lst in by_ed.items():
            if not any(c.untipped_extra_units for c in lst):
                continue
            untipped = [r for r in p.allowed_roles[eid] if r not in p.tipped_roles]
            xs = {x[(eid, r, a)] for c in lst for a in c.work_slots for r in untipped if (eid, r, a) in x}
            if not xs:
                continue
            nt = m.new_bool_var(f"nontip[{eid},{d}]")
            for v in xs:
                m.add(nt >= v)
            for c in lst:
                if c.untipped_extra_units:
                    z = m.new_bool_var("")
                    m.add(z >= y[c.idx] + nt - 1)
                    tip_terms.append((z, c.untipped_extra_units))
        self.tip_terms = tip_terms

        if self.churn and CHURN_DOLLARS > 0:
            for (eid, r, a), v in x.items():
                prev = x.get((eid, r, a - slot))
                if prev is None:
                    churn_terms.append(v)
                else:
                    s = m.new_bool_var("")
                    m.add(s >= v - prev)
                    churn_terms.append(s)

        # coverage & gaps, per sub-interval of a slot where someone may be on a short break
        # (v1.1 per-minute coverage). l[e,r,a,k] = e is on role r at slot a but on break in
        # sub-interval k: l <= x[e,r,a], sum_r l = (e on break at a,k).
        cov: dict[tuple[str, int], list] = {}
        for (eid, r, a), v in x.items():
            cov.setdefault((r, a), []).append(v)
        loss: dict[tuple[str, int, int], list] = {}
        for (eid, a, k), ys in part_brk.items():
            b = sum(ys)
            rs = [r for r in p.allowed_roles[eid] if (eid, r, a) in x]
            if len(rs) == 1:
                loss.setdefault((rs[0], a, k), []).append(b)
                continue
            ls = []
            for r in rs:
                lv = m.new_bool_var("")
                m.add(lv <= x[(eid, r, a)])
                ls.append(lv)
                loss.setdefault((r, a, k), []).append(lv)
            m.add(sum(ls) == b)
        self.loss = loss
        self.subs = subs
        gap = {}
        gap_terms = []
        roles = {r.id: r for r in p.cfg.roles}
        for (r, a), dem in p.demand.items():
            pen = roles[r].gap_penalty_per_hour if r in roles else 0.0
            full = sum(cov.get((r, a), []))
            if not any((r, a, k) in loss for k in range(len(subs))):
                g = m.new_int_var(0, dem, f"gap[{r},{a}]")
                m.add(g + full >= dem)
                gap[(r, a)] = g
                gap_terms.append((g, money(pen * slot_h)))
                continue
            for k, (u0, u1) in enumerate(subs):
                g = m.new_int_var(0, dem, f"gap[{r},{a},{k}]")
                m.add(g + full - sum(loss.get((r, a, k), [])) >= dem)
                gap[(r, a, k)] = g
                gap_terms.append((g, money(pen * (u1 - u0) / 60)))

        soft: list[SoftTerm] = []
        const_units = 0

        # --- per-employee hard rules --------------------------------------------
        weekly_ot = {}
        self.day_ot_terms: list[tuple] = []  # (var, units per minute): daily OT of split days beyond each shift's own
        day_ot_extra: dict[str, list] = {}
        if split:
            self._split_day_sums(m, y, by_ed, day_ot_extra)
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
                m.add(ot >= total - sum(v * d_ for v, _, d_ in terms) - sum(day_ot_extra.get(eid, [])) - thr)
                weekly_ot[eid] = ot

        # --- rest between shifts (always no overlap; plus rules) ------------------
        rest_rules = []  # (minutes, bucket, id, strength, weight, applies)
        for c in p.constraints:
            if c.kind == ConstraintKind.min_rest_between_shifts:
                rest_rules.append((int(c.params["minutes"]), "constraint", c.id, c.strength, c.weight_dollars, c))
        for lr in p.law_of(LawRuleType.min_rest_between_shifts):
            # Engine policy: law rest rules are honored as hard bans (never pay the premium).
            rest_rules.append((int(lr.params["minutes"]), "law", lr.id, Strength.hard, 0.0, None))
        if split:
            first_start, last_end = day_bounds(m, y, by_ed)
            self._same_day_law_rest(m, y, by_ed, n_max)
        for (eid, d), w in works.items():
            nxt = works.get((eid, d + 1))
            if nxt is None:
                continue
            if split:  # across days: from the day's last end to the next day's first start (#23)
                end_d, start_n = last_end[(eid, d)], first_start[(eid, d + 1)]
            else:
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
            elastic = False
            if hard and k == ConstraintKind.always_staffed and self.elastic_always > 0 and not self.assume:
                hard, elastic = False, True
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
                        full = sum(cov.get((rid, a), [])) + self._zero
                        parts = ([(full - sum(loss[(rid, a, kk)]), (u1 - u0) / 60) for kk, (u0, u1) in enumerate(subs)
                                  if (rid, a, kk) in loss] + [(full, slot_h)])
                        if len(parts) > 1:  # sub-intervals with a possible break, then the rest of the slot
                            rest = slot_h - sum(h for _, h in parts[:-1])
                            parts[-1] = (full, rest)
                        for expr, h in parts:
                            if h <= 0:
                                continue
                            if hard:
                                self.add(expr >= 1, g)
                            else:
                                unc = m.new_bool_var("")
                                m.add(expr + unc >= 1)
                                w = self.elastic_always if elastic else con.weight_dollars
                                soft.append(SoftTerm(unc, money(w * h), h, con.id, k.value,
                                                     None, dollars_per=w * h))
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
        self.add(all_paid <= max(int(round(cap_h * 60)), self.min_hours_cap_minutes),
                 self.guard("other", "budget.weekly_hours_cap"))
        wage_expr = sum(y[c.idx] * c.wage_units for c in cands) + sum(z * u for z, u in self.tip_terms) + self._zero
        ot_expr = sum(v * u for v, u in self.day_ot_terms) if self.day_ot_terms else 0
        if weekly_ot:
            mult = p.weekly_ot.params["multiplier"]
            ot_expr += sum(v * money(p.emps[eid].wage_per_hour * (mult - 1) / 60) for eid, v in weekly_ot.items())
        if b.weekly_dollar_cap is not None:
            cap_d = b.weekly_dollar_cap + sum(a.extra_dollars for a in b.approvals)
            self.add(wage_expr + ot_expr <= money(cap_d), self.guard("other", "budget.weekly_dollar_cap"))

        # --- objective ----------------------------------------------------------------
        if not self.assume:
            pref = sum(y[c.idx] * c.pref_units for c in cands if c.pref_units) if cands else 0
            pref += sum(y[c.idx] * c.extra_units for c in cands if c.extra_units) if cands else 0
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

    # --- split days (SEMANTICS #23) ---------------------------------------------------
    def _split_day_sums(self, m, y, by_ed, extra_ot: dict[str, list]) -> None:
        """Per-day quantities over all of a day's shifts: minor daily cap, daily overtime (cap when
        overtime is not allowed; otherwise the OT beyond what each shift already prices)."""
        p = self.p
        dot = p.daily_ot
        for (eid, d), lst in by_ed.items():
            if len(lst) < 2:
                continue
            e = p.emps[eid]
            paid = sum(y[c.idx] * c.paid_min for c in lst)
            cap = p.minor_day_cap(e, d)
            if cap is not None:
                m.add(paid <= cap)
            if dot is None:
                continue
            thr = int(dot.params["threshold_hours"] * 60)
            if not p.cfg.budget.overtime_allowed:
                self.add(paid <= thr, self.guard("law", dot.id))
                continue
            mult = dot.params["multiplier"]
            xo = m.new_int_var(0, 2 * DAY, "")
            m.add(xo >= paid - thr - sum(y[c.idx] * c.daily_ot_min for c in lst))
            extra_ot.setdefault(eid, []).append(xo)
            self.day_ot_terms.append((xo, money(e.wage_per_hour * (mult - 1) / 60)))
            dbl = dot.params.get("double_threshold_hours")
            if dbl is not None:
                dm = int(dbl * 60)
                xd = m.new_int_var(0, 2 * DAY, "")
                m.add(xd >= paid - dm - sum(y[c.idx] * max(0, c.paid_min - dm) for c in lst))
                self.day_ot_terms.append((xd, money(e.wage_per_hour * (2 - mult) / 60)))

    def _same_day_law_rest(self, m, y, by_ed, n_max: int) -> None:
        """A law min_rest_between_shifts rule also holds between two shifts of one day, unless its
        params say `excludes_same_day_split` (SEMANTICS #23)."""
        rules = [lr for lr in self.p.law_of(LawRuleType.min_rest_between_shifts)
                 if not lr.params.get("excludes_same_day_split")]
        if not rules:
            return
        for (eid, d), lst in by_ed.items():
            if len(lst) < 2:
                continue
            ends: dict[int, list] = {}
            starts: dict[int, list] = {}
            for c in lst:
                ends.setdefault(c.abs_end, []).append(y[c.idx])
                starts.setdefault(c.abs_start, []).append(y[c.idx])
            ended = {}
            for t, vs in ends.items():  # shifts never overlap, so at most one ends at t
                b = m.new_bool_var("")
                m.add(b == sum(vs))
                ended[t] = b
            for lr in rules:
                rest = int(lr.params["minutes"])
                g = self.guard("law", lr.id)
                for a, ss in starts.items():
                    win = [b for t, b in ended.items() if a - rest < t <= a]
                    if win:
                        self.add(sum(win) + n_max * sum(ss) <= n_max, g)


def max_shifts_per_day(p: Prep) -> int:
    return max(1, int(getattr(p.cfg.store, "max_shifts_per_day", 1) or 1))


def day_bounds(m: cp_model.CpModel, y: dict, by_ed: dict) -> tuple[dict, dict]:
    """(first start, last end) per (employee, day) over the chosen candidates, as int vars (only
    meaningful when the employee works that day)."""
    first, last = {}, {}
    for k, lst in by_ed.items():
        starts = [c.abs_start for c in lst]
        ends = [c.abs_end for c in lst]
        f = m.new_int_var(min(starts), max(starts), "")
        la = m.new_int_var(min(ends), max(ends), "")
        for c in lst:
            m.add(f <= c.abs_start).only_enforce_if(y[c.idx])
            m.add(la >= c.abs_end).only_enforce_if(y[c.idx])
        first[k], last[k] = f, la
    return first, last


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
    for kv in filter(None, os.environ.get("ENGINE_CPSAT_PARAMS", "").split(",")):  # experiments only
        k, v = kv.split("=")
        cur = getattr(solver.parameters, k)
        setattr(solver.parameters, k, type(cur)(v) if not isinstance(cur, bool) else v.lower() in ("1", "true"))
    if light_presolve:  # full presolve costs ~15 s on the demo store and barely shrinks it
        solver.parameters.max_presolve_iterations = 1
        solver.parameters.cp_model_probing_level = 0
        solver.parameters.symmetry_level = 0
    if hint:
        for v, val in hint.items():
            built.model.add_hint(v, val)
    status = solver.solve(built.model)
    return solver, status


__all__ = ["Builder", "Built", "SoftTerm", "solve", "SCALE", "day_bounds", "max_shifts_per_day"]
