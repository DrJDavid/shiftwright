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
  feasible ~$30.9k demo schedule in ~1.5 s, so CP-SAT always has a solution. The older coarse two-stage strategy was removed (it benchmarked the same; numbers below).
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

**Benchmarks** (`uv run python packages/engine/scripts/bench.py [--single] [--limit 30] [--only tiny|demo|like]`;
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

**fix_day (M2) — done, exported** (`fix.py`; `fix_day(req, time_limit_s=8)`):
- Base = the schedule with the call-outs' shifts on `req.day` removed from `now` on (a call-out whose
  shift started before `now` keeps the part before `now` only if that is ≥ the min shift length;
  otherwise the whole shift is dropped and noted).
- Candidates: one frozen candidate per base shift (other days: forced as is, roles fixed; the day:
  roles before `now` fixed); extensions (later end, or earlier start never before `now`; break layouts
  must keep breaks before `now`); call-ins for people not working that day, not called out, not
  declined, starting ≥ `now` rounded up to the slot (wage + $15 disruption in the objective;
  preferences not charged, SEMANTICS #16). Builder options added: `forced`, `forced_days`,
  `fixed_roles`, `elastic_always` (hard always_staffed priced at $1000/h so a fix always exists),
  `min_hours_cap_minutes` (budget cap never below the frozen hours), `Cand.extra_units`.
- Model N (no call-ins) → `schedule_if_none_accept` + `actions` (extend / reassign / drop_coverage);
  model A (all allowed levers) → `schedule_if_all_accept`; A's call-ins + up to 5 alternates (best
  feasible call-in per person against N's remaining gaps, Python hard checks) form the queue, ranked
  jointly by open gap hours the shift can cover / added $ × (accepted+1)/(offered+2). Queue is empty
  when A picks no call-in (so the API's "filled" works after an accept).
- Demo call-out (Sat 06:04, e034/e052/e053): fix_day ~0.6 s; both schedules 0 hard violations;
  coverage before 92.4–92.7% → worst 93.4–93.6% → best 94.2–94.5%; queue top 2 = e023, e027.
  `scripts/fix_demo.py` prints the plan. Tests: `tests/test_fix.py` (tiny + demo: <10 s, frozen
  past/other days, validator clean, declines excluded, accept → refix keeps the shift).
- Predictive-scheduling premiums (SEMANTICS #17, v1.4 modes) — `premium.py`, params only:
  - applies unless `Store.employer_employee_count` ≤ `applies_if_employees_over`; `applies_to: food`
    skipped (retail); `covered_wage_max_hourly` excludes higher-paid staff. NOT applied (unknown data):
    `min_covered_employees`, `min_local_employees`, `min_locations`, `employee_count_scope`,
    `post_deadline_grace_hours`, `change_premium_window_days`. Fix changes are same-day ⇒ inside the
    notice window and < 24 h notice.
  - added hours (call-in, extension): `premium_flat_dollars`, else `under_24h_tiers`, else
    `change_premium_hours_under_24h`/`change_premium_hours`, pro-rated if `prorate_added_under_1h`,
    capped by `change_premium_hours_max`, free under `grace_minutes`; × wage (regular = scheduled rate
    here). `premium_basis: none` (NYC) ⇒ no premium, noted. Missing hours param ⇒ $0 + "Premium not
    computed: <rule> lacks <param>".
  - call-in exemptions: `coworker_absence_exempt` (SF); else `voluntary_additional_hours_exempt` with
    written consent satisfied by text only if `text_message_counts_as_written` is true (or no written
    requirement); `exemption_requires_group_message` ⇒ only `group_offer` with ≥
    `exemption_min_recipients` queue members; `exemption_only_for_absent_coworker_hours` ⇒ only the
    minutes overlapping the called-out shifts' lost time are exempt, the rest is charged. Extensions are
    always premium-bearing (leader-decided, no written consent). Reassigns are free; the call-out's own
    lost hours are never charged.
  - mode: `FixRequest.outreach_mode`, else the cheaper total premium over A's call-ins (tie one_to_one),
    reported in `FixPlan.outreach_mode`. Call-in and extension premiums are in the CP-SAT objective
    (`extra_units`; call-ins priced at the cheapest allowed mode), in `OutreachCandidate.added_cost_dollars`
    (+ `premium_pay_dollars`, `law_rule_ids`, `premium_note`), `FixAction.premium_pay_dollars` +
    rationale, ranking, and `schedule_if_*.metrics.premium_pay_dollars`.
  - Known: WS2's `validate()` reports `metrics_mismatch` on `premium_pay_dollars` for FWW cities (it
    recomputes only clopen premiums); SEMANTICS #17 says WS2 checks these in a fix-plan check instead.
  - Checked on the demo store moved to Chicago (call-in exempt by text, extensions +1 h) and Seattle
    (one_to_one +min(1 h, added)×wage, group_offer exempt for the absent coworker's hours; mode None
    picks group_offer); fix_day 2–7 s there. Tests: `tests/test_premium.py`.
- `Shift.why` (v1.2, `why.py`): per shift, headline role line ("Keeps Leader on Duty staffed Sat
  8 am–4 pm (c_lod_always)", "Only Cashier on shift …", "Covers Cashier … (needs 2)"), weekly hours
  "32/40 h this week", preferred-on/off overlap, minor note; fix_day prefixes call-in / extension lines.

**Eval fixes this slice:** `bounds.always_staffed_conflict` proves hard always_staffed infeasibility
fast (per-day exact min shifts 1/2/3+ by slot bitmasks vs days the eligible people can work);
S legal_trap CA is genuinely infeasible under our model (4 leaders × 5 days = 20 < 21 shifts needed:
CA daily OT >8 h is not allowed, so 2 shifts can't cover 08–22 plus each other's meal) → reported
in ~3 s naming c_lod_always, c_max_days, shift-length rules, CA meal/rest/daily OT. Caveat: the
proof is relative to the engine's break layouts (rest breaks rounded to 30 min, limited positions).
If CP-SAT finds nothing in time, the greedy schedule is checked by the phase-2 model and returned as
"feasible" (M legal_trap CA: feasible, 81% coverage, only the expected below_minimum_wage).
"infeasible" only when CP-SAT or the bound proves it. Employees in a hard always_staffed role get
flexible rest-break layouts and are not pruned. `ENGINE_WORKERS` env sets CP-SAT workers (default
min(8, cpu)); `ENGINE_LOG=1` logs CP-SAT search. Memory work not done (Railway now 8 GB).

**v1.1 exact breaks — done** (`prep.EXACT_BREAKS`, env `ENGINE_EXACT_BREAKS=0` reverts to slot-rounded):
- Break length = law duration rounded up to 5 min; breaks START on the slot grid (meal placement and
  rest targets rounded to the slot), so a 10-min rest break covers the first 10 min of a slot.
  `Prep.sub` = sub-interval boundaries inside a slot (e.g. [0, 10] → [0,10) and [10,30)); `Cand.part`
  = work slot → bitmask of sub-intervals on break. Slots only partly on break stay working slots.
- Model: `l[e,r,a,k] ≤ x[e,r,a]`, `Σ_r l = (on break at a,k)`; gaps per sub-interval weighted by
  minutes; hard always_staffed per sub-interval (SEMANTICS #18: break ≠ on duty).
- Output: segments tile shift minus breaks exactly (off-grid ends); `coverage_map` per 5-min tick;
  gaps per tick (merged); coverage_pct per minute. Validator agreement tests green (CA exact 10-min).
- tiny_store under CA is now FEASIBLE (7.5 h overlapping leader shifts cover each other's breaks;
  validator 0 hard apart from below_minimum_wage) — WS2's "provably infeasible" note was about
  30-min-rounded breaks. S legal_trap CA is still proven infeasible (needs 21 leader shifts, 20 days).
- Bound / greedy / always_staffed seed are sub-interval aware. Prep 6× faster (break layouts cached per
  length relative to the start, `Break.model_construct`, slot masks from break list): Seattle 20 s → 3 s.

**Very large models (> FULL_MODEL_MAX_CANDS = 100k: Seattle 256k, SF 216k, Chicago 120k):** day-by-day
LNS (`solve._day_lns`): each day re-solved on its full candidate grid with every other day fixed,
hinted with the current week (y and x); falls back to the hourly-grid + greedy-shifts model if the
greedy start is not feasible. 30 s results (coverage / objective): Seattle 89.9–90.2% / $45.5k,
SF 88.9–89.3% / $42.2k, Chicago 91.1% / $34.8k, Austin demo 94.6% / $29.0k; Seattle at 120 s 91.6% /
$43.7k. Much of the Seattle/SF shortfall is priced: e.g. fitting_room ($20/h gap) below the $21.30
minimum wage. fix_day: Chicago 1.1 s, Seattle 5.7 s, SF 4.2 s; validator clean except the known
premium `metrics_mismatch` (#17 fix-plan check pending in WS2) and the fixtures' below_minimum_wage.

**Next steps (in order, coordinator 01:00):**
1. Quality push at 30 s on eval stores (S/M easy/tight/legal_trap, demo stores): greedy repair /
   local search, LNS neighborhoods (days, employees), solver params; LLMs found 5–6% cheaper.
2. Split shifts (SEMANTICS #23, `Store.max_shifts_per_day`), proofs valid under that max.
3. v1.5: tipped pay (#20), age_min, sector applicability (#19).
4. fix_day re-fix candidates priced for the plan's mode (WS6 note).

**Blocked on:** nothing. Rebased onto main 94567f6 (contracts v1.5).

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
