# WS1 status

**Done (M1):**
- `solve_week(config, time_limit_s=20, previous=None)` — CP-SAT, two phases:
  1. choose shifts (one bool `y` per candidate (start, length, break layout) per employee-day) +
     per-slot role assignment `x` + priced gaps + hard/soft rules;
  2. shifts fixed, roles re-assigned with a $0.50/segment churn tiebreak (not in reported objective).
  Phase 1 uses ~85% of `time_limit_s`; phase 2 gets what is left (≤5 s).
- Large models (> `SINGLE_STAGE_MAX_CANDS` = 8 000 candidates, i.e. the demo store) start from a
  **greedy hint** (`greedy.py`: lazy greedy on "gap penalty removed − cost", respects one shift/day,
  weekly caps, budget, max days, rest; hard always_staffed slots weighted $1000/h). It gives a
  feasible ~$30.9k demo schedule in ~1.5 s, so CP-SAT always has a solution. `solve.STRATEGY` can
  be set to `"coarse"` (older two-stage: hourly-grid model first, then full grid hinted) — kept for
  comparison, it benchmarks about the same.
- Speed-ups in this slice (the big wins are the first two):
  - light presolve in `model.solve` (`max_presolve_iterations=1`, probing 0, symmetry 0): full
    presolve took ~15 s of the 30 s on the demo store;
  - candidate pruning in `build_prep(prune=True)`: a candidate longer than the minimum whose first
    or last worked slot has no demand/always_staffed/preferred_on for any of the employee's roles is
    dropped (the trimmed shift is never worse); also drops candidates with no useful slot. Skipped for
    employees under a hard `min_hours_week`. Demo: 123k → 68k candidates. `find_conflicts` uses
    `prune=False`;
  - on-shift per (employee, slot) is a running-sum bool (`on[a] = on[a−slot] + starts − ends`)
    instead of a sum over every covering candidate.
- `Store.school_week` honored (SEMANTICS #8) in `Prep.minor_rules`: None = all minor rules,
  True = school-week rules only, False = non-school rules only; a rule without the key always
  applies. Minor latest end is now per day with the validator's reading
  (`latest_end_before_non_school_day` on Fri/Sat for school-week rules, every day for non-school
  rules, else `latest_end`); `explain` uses the same. Tests: `tests/test_school_week.py`.
- `explain_gap(config, schedule, gap)` — one `GapReason` per employee trained for the role, from
  config + schedule only. Also filled into every gap by `solve_week`.
- `find_conflicts(config)` — hard-only model with one assumption literal per hard `Constraint`, law
  rule, `employee:<id>.max_hours_week`, `budget.weekly_hours_cap`, `budget.weekly_dollar_cap`; maps
  `sufficient_assumptions_for_infeasibility()` to `Infeasibility`. `solve_week` calls it on INFEASIBLE.
- Acceptance tests on WS4's `tiny_store.json` + WS3's resolved packs. `tests/test_validator_agreement.py`
  runs WS2's `validate()` on 6 cases: 0 hard violations, every recomputed metric equal to the
  engine's. The CA cases raise wages to $17 because v1.1 adds `below_minimum_wage` and tiny_store's
  wages are below CA's minimum (the engine never changes wages).
- Metrics follow `contracts/SEMANTICS.md` (v1.1).

**Benchmarks** (`uv run python packages/engine/scripts/bench.py [--single] [--strategy coarse|greedy] [--limit 30] [--only tiny|demo|like]`;
time_limit_s=30, 8 workers, 14-core Mac; CP-SAT is non-deterministic, ±$1k between runs on demo):

| store | setup | wall | objective | best bound | coverage | hard viol. |
|---|---|---|---|---|---|---|
| tiny | any | 0.1 s | $1,271 (optimal) | — | 100% | 0 |
| demo (123k→68k cands) | old single-stage (6cb51b9) | 26 s | $56,750 | $20,870 | 64.4% | 0 |
| demo | old uncommitted two-stage | 26 s | $32,794 | $24,869 | 89.8% | 0 |
| demo | **now (greedy hint)** | 26 s | $28,991–29,284 | ~$23–26k | 93.8–94.3% | 0 |
| demo | now, coarse two-stage | 26 s | $29,225–30,669 | — | 92.5–94.3% | 0 |
| demo | now, single-stage no hint | 26 s | $29,972–31,639 | — | 89.6–92.8% | 0 |
| demo | greedy hint, 120 s limit | 103 s | $27,893 | $26,478 (5.1%) | 94.9% | 0 |
| demo-like (synthetic) | old single-stage | 26 s | $15,693 | $13,273 | 94.0% | 0 |
| demo-like | now (greedy hint) | 26 s | ~$15,070–15,350 | ~$12.6k | 95.5% | 0 |

Demo coverage ceiling is ~95.2% (budget 1,393.5 h vs 1,463 h of demand), so at 30 s we are within
~1 point of max coverage and ~4–5% above the best known schedule. The reported `relative_gap` (~11%)
is mostly a weak bound; ≤1% proven gap in <30 s is NOT reached. Fine for the demo.

**Next steps (in order):**
1. **v1.1 5-minute breaks + per-minute coverage** (`BREAK_GRANULARITY_MINUTES=5`): place breaks at
   5-min resolution with their exact duration (10-min rest = 10 min), make coverage/gap terms per
   minute (a slot with a 10-min break counts 20/30 covered). Probably model demand per slot but
   subtract break-minutes; `output.make_shift` must split RoleSegments at break bounds; metrics
   and `gaps_from_shifts` per minute. Should also fix tiny_store-under-CA infeasibility.
2. **`fix_day` (M2)** — not implemented and NOT exported from `shiftwright_engine` (the API detects
   it by import; don't export a placeholder). Plan: `Builder(cand_ok=...)` restricted to the day,
   existing shifts of other days fixed, call-outs removed; FixPlan.plan_id stays None.
3. Perf if time: better bound (e.g. LP-only worker params) or a second greedy variant; `week_stability`/`previous`.

**Blocked on:** nothing. Rebased onto main fafe76a (contracts v1.1).

**Interpretations / shortcuts (please review — validator WS2 should agree):**
- Hours = paid hours: shift length minus unpaid breaks. Budget hours and `max_hours_week` use paid hours.
- Breaks are deterministic per (start, length):
  - meal: one per meal rule (tier) whose `after_minutes` the shift length exceeds (strict). Placed so
    it ENDS by `latest_start_minute_of_shift` (midpoint if null); the engine also tries the meal 1 h
    and 2 h earlier so overlapping shifts can cover each other. `waivable_under_minutes` ignored
    (we never assume a waiver).
  - rest: floor(span / `per_minutes_worked`), and at least 1 when span ≥ `not_required_under_minutes`
    (WS2 #6); evenly spaced.
  - Break durations are still rounded UP to the slot size, e.g. a 10-min rest break becomes 30 min
    at 30-min slots (valid under v1.1; 5-min breaks are next step 1).
  - If several rest rules exist, the one with the smallest `per_minutes_worked` is used.
  - Known limit: rest-break positions are fixed, so tiny_store under CA (2 leaders + always_staffed)
    comes back infeasible, and the infeasibility names only `c_lod_always`, not the break law
    (break laws are applied when shifts are generated, not as switchable rules). Contract request
    `contracts/requests/ws1-break-granularity.md` was ACCEPTED in v1.1 (next step 1).
- Law `min_rest_between_shifts` is enforced as a hard ban (the engine never pays the premium).
- `minor_limits`: filtered by `Store.school_week` (see above); among the applicable rules the most
  restrictive wins. In school-week rules, Mon–Fri are school days (`max_hours_day`) and Sat/Sun
  are non-school days (`max_hours_non_school_day` if present). `latest_end_summer` unused.
- `minor_prohibited_roles` and `Role.min_age` block the role; reason code `minor_rule`.
- Overtime: if `overtime_allowed=False`, weekly paid hours ≤ weekly OT threshold and shift paid hours
  ≤ daily OT threshold. If allowed, premium = (multiplier−1)×wage per OT hour; daily OT first, weekly
  OT on the remaining hours; above `double_threshold_hours` paid 2×.
- Soft units (WS2 #11): min_rest $/hour missing; min/max shift length $/hour short/over (only for
  lengths the candidate grid generates: hard bounds, else defaults 180–600); always_staffed $/uncovered
  hour; days/consecutive days $/extra day; fair_spread $/excess shift; preferred_role $/hour worked in
  another role; not_together $/overlapping on-shift hour; min_hours_week $/hour short.
- Overlapping `DemandRequirement`s for the same role/slot are SUMMED (WS4 fixtures never overlap,
  so this matches their per-slot reading there).
- `coverage_pct` is 0–100 (covered headcount-hours / required, capped per slot at demand).
- `objective_dollars` = wage (incl. OT premium) + premium pay + gap penalties + soft penalties.
- Shift-length defaults when the config has no hard min/max constraint: 180 / 600 min (product
  default, not law). Soft min/max shift length constraints are ignored.
- `max_consecutive_days` only looks inside the week (no previous-week carry-over).
- `week_stability` and `previous` are not modeled yet.
- Gap reason ordering: if an employee is on shift during the gap they get `already_assigned` (or
  `law_rule` if on a break) before hours/budget checks, since swapping roles doesn't change hours.
  `max_days_per_week` reached → `at_max_hours` with that `constraint_id`.
- Gap times: absolute week minutes are split back into `day`/minute by midnight, so an overnight
  gap shows on the next day.
