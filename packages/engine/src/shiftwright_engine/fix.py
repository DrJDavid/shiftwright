"""fix_day: re-plan one day after call-outs (briefs/WS1-engine.md "Fixer", SEMANTICS #16).

Frozen: every other day, and everything before `now` on the day (shift starts, breaks and roles).
The called-out shifts are removed from `now` on. Levers:
  - reassign: roles after `now` may change for people on shift (free, plus the churn tiebreak);
  - extend: a shift may end later (or, if it hasn't started, start earlier, never before `now`);
  - call_in: a new shift for someone not working today, starting at or after `now`
    (wage + CALL_IN_DISRUPTION_DOLLARS + any predictive-scheduling premium; preferences not charged);
  - drop_coverage: leave the gap (its penalty).
Two models are solved on the week (other days fixed): N without call-ins (`schedule_if_none_accept`,
and the immediate `actions`) and A with every allowed lever (`schedule_if_all_accept`; its call-ins
head the `outreach_queue`). Alternates are the next best call-ins against N's remaining gaps.
Ranking (SEMANTICS #16): gap hours the shift can cover per added dollar × est_accept_prob.
"""
from __future__ import annotations

import time
from typing import Optional

from ortools.sat.python import cp_model

from shiftwright_contracts.models import (
    AvailabilityKind,
    Break,
    ConstraintKind,
    FixAction,
    FixPlan,
    FixRequest,
    Gap,
    LawRuleType,
    Lever,
    OutreachCandidate,
    RoleSegment,
    Schedule,
    Shift,
    Strength,
)

from .explain import explain_with_prep
from .premium import MODES, Premium, call_in_premium, extension_premium
from .why import DAYS, annotate, span
from .model import Builder, solve
from .output import (
    availability_violations,
    compute_metrics,
    coverage_map,
    slot_min_cov,
    gaps_from_shifts,
    make_shift,
    paid_minutes,
    soft_from_solution,
)
from .prep import DAY, SCALE, Cand, Prep, _avail_for_day, _round_down, _round_up, break_variants, build_prep, make_cand, money

CALL_IN_DISRUPTION_DOLLARS = 15.0  # per call-in, ranking/objective only (not a wage)
ELASTIC_ALWAYS_DOLLARS_PER_HOUR = 1000.0  # always_staffed during a fix: priced, so a fix always exists
MAX_ALTERNATES = 5


def _prob(e) -> float:
    a = e.attendance
    return (a.callins_accepted_90d + 1) / (a.callins_offered_90d + 2)


def _clip(sh: Shift, end: int) -> Shift:
    segs = [RoleSegment(role_id=g.role_id, start=g.start, end=min(g.end, end)) for g in sh.segments if g.start < end]
    brks = [b for b in sh.breaks if b.end <= end]
    return sh.model_copy(update={"end": end, "segments": segs, "breaks": brks})


def _roles_of(sh: Shift, slot: int) -> dict[int, str]:
    out = {}
    for g in sh.segments:
        t = g.start - g.start % slot
        while t < g.end:
            out[sh.day * DAY + t] = g.role_id
            t += slot
    return out


class _Fix:
    def __init__(self, req: FixRequest):
        self.req = req
        self.cfg = req.config
        self.d = req.day
        self.now = req.now
        self.p = build_prep(self.cfg, with_cands=False)
        p = self.p
        self.slot = p.slot
        self.now_up = _round_up(self.now, self.slot)
        self.levers = set(req.allowed_levers)
        self.callout_ids = {c.employee_id for c in req.callouts if c.day == self.d}
        self.declined = set(req.declined_employee_ids)
        self.notes: list[str] = []

        # Schedule after the call-outs: their shifts on the day are removed from `now` on.
        self.base: list[Shift] = []
        self.absent_spans: list[tuple[int, int]] = []  # called-out coworkers' lost time today (day minutes)
        for sh in req.schedule.shifts:
            if sh.employee_id in self.callout_ids and sh.day == self.d and sh.end > self.now:
                self.absent_spans.append((max(sh.start, self.now), sh.end))
                lo, _ = p.shift_bounds(sh.employee_id)
                cut = _round_down(self.now, self.slot)
                if sh.start < cut and cut - sh.start >= lo:
                    self.base.append(_clip(sh, cut))
                elif sh.start < self.now:
                    self.notes.append(f"{sh.employee_id}'s shift started before the call-out but is dropped "
                                      f"whole: the part already worked is shorter than the minimum shift.")
                continue
            self.base.append(sh)
        self.orig = {(s.employee_id, s.day): s for s in self.base}

        # Candidates: one frozen candidate per base shift, plus extensions and call-ins on the day.
        self.frozen_idx: dict[tuple[str, int], int] = {}
        self.fixed_roles: dict[tuple[str, int], str] = {}
        self.ext: set[int] = set()
        self.callin: set[int] = set()
        for sh in self.base:
            e = p.emps.get(sh.employee_id)
            if e is None:
                continue
            c = self._add(make_cand(p, e, sh.day, sh.start, sh.end, list(sh.breaks), [], 10 ** 9, None,
                                    charge_preferences=True, strict=False))
            c.pref_units = 0  # existing shift: preference already accepted when it was scheduled
            self.frozen_idx[(sh.employee_id, sh.day)] = c.idx
            roles = _roles_of(sh, self.slot)
            for a, r in roles.items():
                if sh.day != self.d or a < self.d * DAY + self.now or Lever.reassign not in self.levers:
                    self.fixed_roles[(sh.employee_id, a)] = r
            if sh.day == self.d and Lever.extend in self.levers and sh.end > self.now:
                self._extensions(e, sh)
            if sh.employee_id not in p.allowed_roles or not set(sh_roles(sh)) <= set(p.allowed_roles[sh.employee_id]):
                # Keep their roles exactly as given (we can't re-derive a role they may not normally work).
                for a, r in roles.items():
                    self.fixed_roles[(sh.employee_id, a)] = r
        if Lever.call_in in self.levers:
            working = {s.employee_id for s in self.base if s.day == self.d}
            for e in self.cfg.employees:
                if (e.id in working or e.id in self.callout_ids or e.id in self.declined
                        or not p.allowed_roles.get(e.id)):
                    continue
                self._callins(e)
        self.forced_days = set(self.frozen_idx)

    # ------------------------------------------------------------------ candidates
    def _add(self, c: Cand) -> Cand:
        c.idx = len(self.p.cands)
        self.p.cands.append(c)
        self.p.by_emp_day.setdefault((c.emp, c.day), []).append(c)
        return c

    def _limits(self, e, day):
        p = self.p
        minors = p.minor_rules(e)
        earliest = max([r.params["earliest_start"] for r in minors if r.params.get("earliest_start") is not None],
                       default=None)
        avail = list(_avail_for_day(p, e, day))
        unavail = [(a.start, a.end) for a in avail if a.kind == AvailabilityKind.unavailable]
        return earliest, p.minor_latest_end(e, day), p.minor_day_cap(e, day), avail, unavail

    def _ok_span(self, e, day, start, end, earliest, latest_end, unavail) -> bool:
        w0, w1 = self.p.windows.get(day, (0, 0))
        lo, hi = self.p.shift_bounds(e.id)
        if start < w0 - w0 % self.slot or end > w1 or not lo <= end - start <= hi:
            return False
        if earliest is not None and start < earliest:
            return False
        if latest_end is not None and end > latest_end:
            return False
        return not any(a < end and start < b for a, b in unavail)

    def _extensions(self, e, sh: Shift) -> None:
        p, s = self.p, self.slot
        earliest, latest_end, day_cap, avail, unavail = self._limits(e, sh.day)
        week_cap = min(c for c, _, _ in p.effective_max_minutes(e))
        starts = [sh.start]
        if sh.start >= self.now_up + s:
            starts += list(range(max(self.now_up, p.windows[sh.day][0]), sh.start, s))
        _, hi = p.shift_bounds(e.id)
        ends = [sh.end] + list(range(sh.end + s, sh.start + hi + 1, s))
        past = {(b.start, b.end) for b in sh.breaks if b.start < self.now}
        for st in starts:
            for en in ends:
                if (st, en) == (sh.start, sh.end) or not self._ok_span(e, sh.day, st, en, earliest, latest_end, unavail):
                    continue
                for brks in break_variants(p, st, en - st, True):
                    if {(b.start, b.end) for b in brks if b.start < self.now} != past:
                        continue
                    c = make_cand(p, e, sh.day, st, en, brks, avail, week_cap, day_cap, charge_preferences=False)
                    if c is not None:
                        c.extra_units = money(extension_premium(p, e, max(0, c.paid_min - paid_minutes(sh))).dollars)
                        self.ext.add(self._add(c).idx)

    def _callins(self, e) -> None:
        p, s, d = self.p, self.slot, self.d
        if d not in p.windows:
            return
        earliest, latest_end, day_cap, avail, unavail = self._limits(e, d)
        week_cap = min(c for c, _, _ in p.effective_max_minutes(e))
        lo, hi = p.shift_bounds(e.id)
        w0, w1 = p.windows[d]
        useful = {a for (r, a) in p.demand if r in p.allowed_roles[e.id] and a // DAY == d}
        modes = [self.req.outreach_mode] if self.req.outreach_mode else list(MODES)
        for st in range(max(self.now_up, _round_up(w0, s)), w1, s):
            for length in range(lo, hi + 1, s):
                en = st + length
                if en > w1:
                    break
                if not self._ok_span(e, d, st, en, earliest, latest_end, unavail):
                    continue
                for brks in break_variants(p, st, length, False):
                    c = make_cand(p, e, d, st, en, brks, avail, week_cap, day_cap, charge_preferences=False)
                    if c is None or not useful.intersection(c.work_slots):
                        continue
                    if length > lo and (c.work_slots[0] not in useful or c.work_slots[-1] not in useful):
                        continue
                    # Model price: cheapest allowed mode (the plan's mode is chosen after the solve).
                    prem = min(self.premium(c, m, 10 ** 6).dollars for m in modes)
                    c.extra_units = money(CALL_IN_DISRUPTION_DOLLARS + prem)
                    self.callin.add(self._add(c).idx)

    def premium(self, c: Cand, mode: str, n_recipients: int) -> Premium:
        return call_in_premium(self.p, self.p.emps[c.emp], c.start, c.end, c.paid_min, mode,
                               self.absent_spans, n_recipients)

    # ------------------------------------------------------------------ solving
    def _solve(self, allow: set[int], forced: set[int], time_limit_s: float, churn: bool = True):
        p = self.p
        frozen = set(self.frozen_idx.values())
        ok = frozen | allow
        hours_floor = sum(p.cands[i].paid_min for i in frozen)
        forced_days = {k for k, i in self.frozen_idx.items()}
        b = Builder(p, cand_ok=lambda c: c.idx in ok, churn=churn, forced=(frozen - self._replaceable()) | forced,
                    fixed_roles=self.fixed_roles, elastic_always=ELASTIC_ALWAYS_DOLLARS_PER_HOUR,
                    min_hours_cap_minutes=hours_floor, forced_days=forced_days).build()
        s, st = solve(b, time_limit_s)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        return b, s, st

    def _replaceable(self) -> set[int]:
        """Frozen candidates an extension may replace (same employee, the fix day)."""
        emps = {self.p.cands[i].emp for i in self.ext}
        return {i for (eid, day), i in self.frozen_idx.items() if day == self.d and eid in emps}

    def _shifts(self, b, s) -> list[Shift]:
        p = self.p
        out = []
        for c in p.cands:
            v = b.y.get(c.idx)
            if v is None or not s.boolean_value(v):
                continue
            orig = self.orig.get((c.emp, c.day))
            if c.idx in self.frozen_idx.values() and (c.day != self.d or Lever.reassign not in self.levers):
                out.append(orig)
                continue
            roles_at = {}
            for a in c.work_slots:
                for r in p.allowed_roles.get(c.emp, []) + ([self.fixed_roles[(c.emp, a)]] if (c.emp, a) in self.fixed_roles else []):
                    xv = b.x.get((c.emp, r, a))
                    if xv is not None and s.boolean_value(xv):
                        roles_at[a] = r
                        break
            if len(roles_at) < len(c.work_slots):
                out.append(orig)  # no role vars (e.g. untrained role kept as given)
                continue
            sh = make_shift(p, c, roles_at)
            if orig is not None:
                sh = sh.model_copy(update={"id": orig.id})
            else:
                sh = sh.model_copy(update={"id": f"{sh.id}-callin"})
            out.append(sh)
        return out

    def _why_extra(self, shifts: list[Shift]) -> dict[str, list[str]]:
        out = {}
        who = ", ".join(sorted(self.callout_ids)) or "nobody"
        for sh in shifts:
            o = self.orig.get((sh.employee_id, sh.day))
            if sh.day != self.d:
                continue
            if o is None:
                out[sh.id] = [f"Call-in for {DAYS[sh.day]} {span(sh.start, sh.end)} after call-outs by {who}"]
            elif (o.start, o.end) != (sh.start, sh.end):
                out[sh.id] = [f"Extended from {span(o.start, o.end)} to {span(sh.start, sh.end)} after call-outs by {who}"]
        return out

    def _schedule(self, shifts: list[Shift], b=None, s=None, status: str = "feasible",
                  premium_pay: float = 0.0) -> Schedule:
        p = self.p
        shifts = annotate(p, shifts, self._why_extra(shifts))
        soft = (soft_from_solution(b, s) if b is not None else []) + availability_violations(p, shifts)
        soft = [v for v in soft if not (v.constraint_id and any(
            c.id == v.constraint_id and c.strength == Strength.hard for c in p.constraints))]
        gaps = gaps_from_shifts(p, shifts)
        sched = Schedule(store_id=self.cfg.store.id, week_start=self.cfg.store.week_start,
                         config_version=self.cfg.config_version, produced_by="engine", status=status,
                         shifts=shifts, soft_violations=soft)
        for g in gaps:
            g.reasons = explain_with_prep(p, sched, g)
        sched.gaps = gaps
        sched.metrics = compute_metrics(p, shifts, soft, gaps, premium_pay=premium_pay)
        return sched

    def extension_premiums(self, shifts: list[Shift]) -> dict[str, Premium]:
        out = {}
        for sh in shifts:
            o = self.orig.get((sh.employee_id, sh.day))
            if sh.day == self.d and o is not None and (o.start, o.end) != (sh.start, sh.end):
                out[sh.employee_id] = extension_premium(self.p, self.p.emps[sh.employee_id],
                                                        max(0, paid_minutes(sh) - paid_minutes(o)))
        return out

    # ------------------------------------------------------------------ outreach
    def _residual(self, shifts: list[Shift]) -> dict[tuple[str, int], int]:
        cov = coverage_map(self.p, shifts)
        out = {}
        for (r, a), dem in self.p.demand.items():
            if a // DAY == self.d:
                have = slot_min_cov(self.p, cov, r, a)
                if dem > have:
                    out[(r, a)] = dem - have
        return out

    def _feasible_callin(self, c: Cand, shifts: list[Shift]) -> bool:
        """Python checks of the hard rules a single added call-in could break, given `shifts`."""
        p = self.p
        mine = [s for s in shifts if s.employee_id == c.emp]
        e = p.emps[c.emp]
        if sum(paid_minutes(s) for s in mine) + c.paid_min > min(cap for cap, _, _ in p.effective_max_minutes(e)):
            return False
        b = self.cfg.budget
        cap = int(round((b.weekly_hours_cap + sum(a.extra_hours for a in b.approvals)) * 60))
        if sum(paid_minutes(s) for s in shifts) + c.paid_min > cap:
            return False
        days = {s.day for s in mine} | {c.day}
        for con in p.constraints:
            if con.strength != Strength.hard or not p.applies(con, c.emp):
                continue
            if con.kind == ConstraintKind.max_days_per_week and len(days) > int(con.params["days"]):
                return False
            if con.kind == ConstraintKind.max_consecutive_days:
                lim, run = int(con.params["days"]), 0
                for dd in range(7):
                    run = run + 1 if dd in days else 0
                    if run > lim:
                        return False
        rest = [int(con.params["minutes"]) for con in p.constraints
                if con.kind == ConstraintKind.min_rest_between_shifts and con.strength == Strength.hard
                and p.applies(con, c.emp)]
        rest += [int(r.params["minutes"]) for r in p.law_of(LawRuleType.min_rest_between_shifts)]
        need = max(rest, default=0)
        for s in mine:
            a0, a1 = s.day * DAY + s.start, s.day * DAY + s.end
            if a0 < c.abs_end and c.abs_start < a1:
                return False
            if s.day == c.day - 1 and c.abs_start - a1 < need:
                return False
            if s.day == c.day + 1 and a0 - c.abs_end < need:
                return False
        for con in p.constraints:
            if con.kind == ConstraintKind.not_together and con.strength == Strength.hard and c.emp in con.params.get("employee_ids", []):
                other = [x for x in con.params.get("employee_ids", []) if x != c.emp]
                for s in shifts:
                    if s.employee_id in other and s.day * DAY + s.start < c.abs_end and c.abs_start < s.day * DAY + s.end:
                        return False
        return True

    def _open_hours(self, c: Cand, residual) -> float:
        """Hours of c's worked slots where one of the employee's roles has an open gap."""
        rs = self.p.allowed_roles[c.emp]
        return sum(self.slot / 60 for a in c.work_slots if any(residual.get((r, a), 0) > 0 for r in rs))

    def _best_callin(self, eid: str, residual, shifts) -> Optional[tuple[Cand, dict[int, str], float, float]]:
        """Best call-in shift for eid against `residual` gaps: (cand, roles, gap hours covered, net $)."""
        p = self.p
        pen = {r.id: r.gap_penalty_per_hour * self.slot / 60 for r in self.cfg.roles}
        best = None
        for c in p.by_emp_day.get((eid, self.d), []):
            if c.idx not in self.callin or not self._feasible_callin(c, shifts):
                continue
            gain, hours, roles = 0.0, 0.0, {}
            for a in c.work_slots:
                opts = [(pen.get(r, 0), r) for r in p.allowed_roles[eid] if residual.get((r, a), 0) > 0]
                if opts:
                    v, r = max(opts)
                    gain += v
                    hours += self.slot / 60
                    roles[a] = r
                else:
                    roles[a] = p.allowed_roles[eid][0]
            net = gain - (c.wage_units + c.extra_units) / SCALE
            if hours > 0 and (best is None or net > best[3]):
                best = (c, roles, hours, net)
        return best

    def _candidate(self, rank: int, c: Cand, shift: Shift, hours: float, prem: Premium) -> OutreachCandidate:
        e = self.p.emps[c.emp]
        cost = round(c.wage_units / SCALE + prem.dollars, 2)
        a = e.attendance
        roles = sorted({g.role_id for g in shift.segments})
        why = (f"Can cover {hours:g} h of open {', '.join(roles)} time on {shift.start // 60:02d}:{shift.start % 60:02d}–"
               f"{shift.end // 60:02d}:{shift.end % 60:02d} for ${cost:,.2f}; accepted "
               f"{a.callins_accepted_90d} of {a.callins_offered_90d} call-ins in the last 90 days.")
        if prem.dollars > 0:
            why += f" Includes ${prem.dollars:,.2f} predictability pay."
        return OutreachCandidate(rank=rank, employee_id=c.emp, proposed_shift=shift, added_cost_dollars=cost,
                                 est_accept_prob=round(_prob(e), 4), why=why, premium_pay_dollars=prem.dollars,
                                 law_rule_ids=prem.law_rule_ids, premium_note=prem.note)


def sh_roles(sh: Shift) -> list[str]:
    return [g.role_id for g in sh.segments]


def _actions(fx: _Fix, none_shifts: list[Shift], none_sched: Schedule,
             ext_prem: dict[str, Premium]) -> list[FixAction]:
    p, d, slot = fx.p, fx.d, fx.slot
    out: list[FixAction] = []
    for sh in none_shifts:
        if sh.day != d:
            continue
        orig = fx.orig.get((sh.employee_id, d))
        if orig is None:
            continue
        e = p.emps[sh.employee_id]
        if (sh.start, sh.end) != (orig.start, orig.end):
            added = (paid_minutes(sh) - paid_minutes(orig)) / 60 * e.wage_per_hour
            pm = ext_prem.get(sh.employee_id, Premium())
            spans = [(sh.start, orig.start)] if sh.start < orig.start else []
            spans += [(orig.end, sh.end)] if sh.end > orig.end else []
            roles = [g.role_id for g in sh.segments if any(g.start < b and a < g.end for a, b in spans)]
            out.append(FixAction(lever=Lever.extend, employee_id=sh.employee_id, role_id=roles[0] if roles else None,
                                 start=spans[0][0], end=spans[-1][1], added_cost_dollars=round(added, 2),
                                 premium_pay_dollars=pm.dollars, law_rule_ids=pm.law_rule_ids,
                                 rationale=f"Extend {sh.employee_id} from {orig.start // 60:02d}:{orig.start % 60:02d}–"
                                           f"{orig.end // 60:02d}:{orig.end % 60:02d} to {sh.start // 60:02d}:"
                                           f"{sh.start % 60:02d}–{sh.end // 60:02d}:{sh.end % 60:02d}; no consent "
                                           f"text needed since they are already on the schedule today." + (f" {pm.note}" if pm.note else "")))
        before, after = _roles_of(orig, slot), _roles_of(sh, slot)
        run = None
        for a in sorted(after):
            changed = a >= d * DAY + fx.now and a in before and before[a] != after[a]
            if changed and run and run[1] == a and run[2] == after[a] and run[3] == before[a]:
                run[1] = a + slot
            elif changed:
                if run:
                    out.append(_reassign(sh.employee_id, run, d))
                run = [a, a + slot, after[a], before[a]]
            elif run:
                out.append(_reassign(sh.employee_id, run, d))
                run = None
        if run:
            out.append(_reassign(sh.employee_id, run, d))
    if Lever.drop_coverage in fx.levers:
        for g in none_sched.gaps:
            if g.day == d and g.end > fx.now:
                out.append(FixAction(lever=Lever.drop_coverage, role_id=g.role_id, start=g.start, end=g.end,
                                     added_cost_dollars=round(g.penalty_dollars, 2),
                                     rationale=f"Leave {g.missing_headcount} {g.role_id} short "
                                               f"{g.start // 60:02d}:{g.start % 60:02d}–{g.end // 60:02d}:"
                                               f"{g.end % 60:02d} (gap penalty ${g.penalty_dollars:,.2f}) "
                                               f"unless a call-in accepts."))
    return out


def _reassign(eid: str, run, d: int) -> FixAction:
    a0, a1, new, old = run
    s, e = a0 - d * DAY, a1 - d * DAY
    return FixAction(lever=Lever.reassign, employee_id=eid, role_id=new, start=s, end=e, added_cost_dollars=0.0,
                     rationale=f"Move {eid} from {old} to {new} {s // 60:02d}:{s % 60:02d}–{e // 60:02d}:{e % 60:02d} "
                               f"to cover the call-out.")


def fix_day(req: FixRequest, time_limit_s: float = 8) -> FixPlan:
    t0 = time.perf_counter()
    fx = _Fix(req)
    base_sched = fx._schedule(list(fx.base))
    per = max(1.0, (time_limit_s - (time.perf_counter() - t0)) * 0.4)

    # N: no call-ins.
    rN = fx._solve(fx.ext, set(), per)
    if rN is None:
        none_shifts, none_sched = list(fx.base), base_sched
        ext_N = {}
    else:
        none_shifts = fx._shifts(rN[0], rN[1])
        ext_N = fx.extension_premiums(none_shifts)
        none_sched = fx._schedule(none_shifts, rN[0], rN[1], "optimal" if rN[2] == cp_model.OPTIMAL else "feasible",
                                  premium_pay=sum(x.dollars for x in ext_N.values()))

    # A: every allowed lever.
    picked: list[int] = []
    all_shifts, rA = none_shifts, None
    if Lever.call_in in fx.levers and fx.callin:
        rA = fx._solve(fx.ext | fx.callin, set(), max(1.0, (time_limit_s - (time.perf_counter() - t0)) * 0.7))
        if rA is not None:
            picked = [i for i in fx.callin if rA[1].boolean_value(rA[0].y[i])]
            if picked:
                all_shifts = fx._shifts(rA[0], rA[1])

    # Outreach pool: A's call-ins, then up to MAX_ALTERNATES alternates against N's remaining gaps.
    pool = []  # (cand, shift, open hours)
    residual = fx._residual(none_shifts)
    by_emp_shift = {(s.employee_id, s.day): s for s in all_shifts}
    for i in picked:
        c = fx.p.cands[i]
        pool.append((c, by_emp_shift[(c.emp, c.day)], fx._open_hours(c, residual)))
    if picked:
        taken = {fx.p.cands[i].emp for i in picked}
        alts = []
        for e in fx.cfg.employees:
            if e.id in taken:
                continue
            best = fx._best_callin(e.id, residual, none_shifts)
            if best is None:
                continue
            c, roles, hours, _net = best
            alt = make_shift(fx.p, c, roles).model_copy(update={"id": f"sh-{e.id}-d{fx.d}-callin"})
            alt = annotate(fx.p, none_shifts + [alt], fx._why_extra([alt]))[-1]
            alts.append((-(hours / max(c.wage_units / SCALE, 0.01)) * _prob(e), c.emp, (c, alt, hours)))
        alts.sort(key=lambda t: (t[0], t[1]))
        pool += [t[2] for t in alts[:MAX_ALTERNATES]]

    # Mode: the requested one, else the cheaper total premium over A's call-ins (tie: one_to_one).
    n = len(pool)
    if req.outreach_mode:
        mode = req.outreach_mode
    else:
        cost = {m: sum(fx.premium(c, m, n).dollars for c, _, _ in pool[:max(1, len(picked))]) for m in MODES}
        mode = "group_offer" if cost["group_offer"] < cost["one_to_one"] else "one_to_one"
    prem = {c.idx: fx.premium(c, mode, n) for c, _, _ in pool}

    # One ranking for picked call-ins and alternates (SEMANTICS #16): open hours / added $ × P(accept).
    def score(item):
        c, _, h = item
        return -(h / max(c.wage_units / SCALE + prem[c.idx].dollars, 0.01)) * _prob(fx.p.emps[c.emp])
    pool.sort(key=lambda t: (score(t), t[0].emp))
    queue = [fx._candidate(k + 1, c, sh, h, prem[c.idx]) for k, (c, sh, h) in enumerate(pool)]

    all_sched = none_sched
    if picked:
        ext_A = fx.extension_premiums(all_shifts)
        callin_prem = sum(prem[i].dollars for i in picked)
        all_sched = fx._schedule(all_shifts, rA[0], rA[1], "optimal" if rA[2] == cp_model.OPTIMAL else "feasible",
                                 premium_pay=sum(x.dollars for x in ext_A.values()) + callin_prem)

    return FixPlan(
        outreach_mode=mode if pool else (req.outreach_mode or "one_to_one"),
        actions=_actions(fx, none_shifts, none_sched, ext_N),
        outreach_queue=queue,
        schedule_if_all_accept=all_sched,
        schedule_if_none_accept=none_sched,
        coverage_before_pct=base_sched.metrics.coverage_pct,
        coverage_after_best_pct=all_sched.metrics.coverage_pct,
        coverage_after_worst_pct=none_sched.metrics.coverage_pct,
    )


__all__ = ["fix_day", "CALL_IN_DISRUPTION_DOLLARS"]
