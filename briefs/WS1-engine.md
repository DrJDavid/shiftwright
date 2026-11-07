# WS1 — Engine (solver, fixer, explanations)

**Folder:** `packages/engine/` (`shiftwright_engine`) · **Oversight:** partner
**Read first:** `SPEC.md`, `contracts/models.py`

## Goal
Given a `StoreConfig` (with `law_pack` filled in), return the minimum-cost `Schedule` that satisfies
every hard rule, with priced gaps and machine-readable reasons. Given a call-out, return a `FixPlan`.

## Public interface (this is all other workstreams may call)
```python
solve_week(config: StoreConfig, time_limit_s: float = 20, previous: Schedule | None = None) -> Schedule
fix_day(req: FixRequest, time_limit_s: float = 8) -> FixPlan
explain_gap(config: StoreConfig, schedule: Schedule, gap: Gap) -> list[GapReason]   # also filled in solve_week
find_conflicts(config: StoreConfig) -> Infeasibility | None   # hard-only feasibility check
```

## Model (recommended approach; deviate only with a note in STATUS.md)
1. **Candidate shifts.** For each employee and day, enumerate (start, length) on the slot grid within
   staff hours, min/max shift length, availability `unavailable` windows, and minor time-of-day limits.
   One bool `y[e,c]` per candidate; at most 1 shift per employee per day. (Roughly 300 candidates per
   employee-day at 30-min slots is fine.)
2. **Breaks.** Breaks are placed deterministically from the shift's length and the law pack: a meal
   break at the latest legal start (or the midpoint if no rule), rest breaks evenly spaced. A
   candidate's working slots exclude its breaks. Paid breaks count toward hours and cost.
3. **Role assignment.** Bool `x[e,r,t]` for each trained role r, only where the employee is on a
   working slot: `Σ_r x[e,r,t] = working(e,t)`. Skip roles blocked by `min_age` or
   `minor_prohibited_roles`.
4. **Coverage.** `covered[r,t] = Σ_e x[e,r,t]`; `gap[r,t] ≥ demand[r,t] - covered[r,t]`, `gap ≥ 0`.
   Penalty = gap × slot_hours × `gap_penalty_per_hour`. `always_staffed` is hard.
5. **Hard rules.** Weekly max hours, budget hours cap (+ approvals), optional dollar cap, overtime
   off when `overtime_allowed=False` (based on the law pack's OT thresholds), min rest between shifts,
   max days per week, max consecutive days, minor hour/day limits.
6. **Soft rules.** Each soft `Constraint` and availability preference adds `weight_dollars × amount`.
   Part-timer min hours: penalty per hour short. `fair_spread`: penalty per occurrence over the max.
7. **Objective (dollars, integer cents):** wages + OT premium + law premiums + gap penalties + soft penalties.
8. **Role churn.** Add a small tiebreak penalty (e.g. $0.50) per role change within a shift so
   assignments don't flicker between roles.

## Explanations (must be facts from the model, not guesses)
For every gap, for every employee **trained** in that role, give one `GapReason`: check in order
`unavailable`, `minor_rule`/`law_rule`, `rest_rule`, `at_max_hours`, `already_assigned` (and to
which role), `budget_cap`, otherwise `cheaper_to_leave_gap`. Compute this after solving, from the
solution and the config.

## Infeasibility
Use CP-SAT assumption literals: one per hard `Constraint`, per law rule, per employee max-hours,
and for the budget. On INFEASIBLE, call `sufficient_assumptions_for_infeasibility()` and map the
result to `Infeasibility`. Gaps can never cause infeasibility, since they are soft.

## Fixer
Freeze everything before `now` and every other day. Remove the called-out shifts from `now`
onward. Re-solve the day with these levers, each with a cost:
- **reassign:** free, plus the churn penalty
- **extend:** wage, plus OT if any
- **drop_coverage:** gap penalty
- **call_in:** wage, plus a disruption cost ($15), plus predictive-scheduling premium if the law pack has one

Also minimize the number of changes to people still on shift. Output:
- `actions`: extend, reassign, and drop actions
- `outreach_queue`: the call-in candidates the solver picked, plus the next-best alternates (up
  to 5), each with its proposed shift. `est_accept_prob = (accepted+1)/(offered+2)`. Rank by
  expected coverage gained per dollar × acceptance probability.
- `schedule_if_all_accept` / `schedule_if_none_accept`

`declined_employee_ids` are excluded. The backend calls `fix_day` again after each decline.

## Acceptance tests (write first)
- tiny_store: solves OPTIMAL in under 2 s; validator (WS2) reports 0 hard violations.
- With nobody trained as cashier: status is still optimal/feasible, cashier gaps exist with their full penalty, and those gaps have an empty `reasons` list.
- A cashier gap while trained cashiers exist has one `GapReason` per trained cashier.
- A minor (age 17) trained on `pit_operator` is never assigned to it.
- Budget cap of 10 hours on tiny_store: total hours ≤ 10, gaps priced.
- A contradictory hard set (e.g. `always_staffed` on a role nobody is trained for) → `infeasible`, with that constraint id in `conflicting_constraint_ids`.
- Demo store (~60 staff, 30-min slots): `solve_week` under 30 s, gap ≤ 1% of objective (report the bound).
- Fixer on the demo call-out scenario: under 10 s; nothing before `now` changes.

## Out of scope
LLM calls, HTTP, persistence, law lookup (you receive the resolved `law_pack`).
