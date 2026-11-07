# WS2 status — validator

Contracts: **v1.4** (`contracts/SEMANTICS.md`). The validator follows it item by item
(#18 *always_staffed excludes breaks* = what the validator already does).

**Done:**
- `validate(config, schedule) -> ValidationReport`, `parse_schedule_lenient(raw)`,
  `recompute_metrics(config, schedule)`, plus `validate_raw(config, raw)` (parse + validate in one
  call, parse problems included; meant for WS5 baseline outputs).
- One check function per `ViolationCode` (`checks.py`, `ALL_CHECKS`), plain loops. Constraint
  measurements are shared by hard checks and soft pricing (`measure.py`). Only `confirmed`
  constraints count.
- Never crashes. Shifts with insane fields are reported `malformed` and skipped by the other checks.
  Each check runs inside a guard that turns an unexpected exception into a hard `malformed`
  violation, and the fuzz tests fail if that guard ever fires.
- v1.1 slice:
  - Breaks on the 5-minute grid (`BREAK_GRANULARITY_MINUTES`). Segment edges may be on that grid
    only where they equal a break start/end; shift start/end stay on `slot_minutes`. Anything else is `malformed`.
  - Coverage and gap penalty per minute (sweep over interval breakpoints in `metrics.coverage`).
    `always_staffed` gaps are per minute too (a 10-min leader break = a 10-min gap). Slot-aligned
    schedules give the same numbers as before (tested).
  - Exactly-10-minute rest breaks satisfy a 10-minute rule.
  - `Store.school_week`: None = all minor rules, True = school-week rules only, False = non-school
    rules only (no school days). A rule without a `school_week` key applies in every mode.
  - `below_minimum_wage`: one hard violation per *scheduled* employee with wage < minimum, with
    `law_rule_id`. "In effect on week_start" = for each jurisdiction (level/state/city) the latest
    rule with `effective <= week_start`, then the highest of those. A rule with no readable date
    counts as in effect.
- **`validate_fix(request: FixRequest, plan: FixPlan) -> ValidationReport`** (`fix.py`, v1.4 slice;
  SEMANTICS #16/#17). One report for the plan; `recomputed_metrics` = schedule_if_all_accept's. Checks:
  - outreach_mode matches the request (when set); each extend/reassign action is in
    schedule_if_none_accept (its span worked, its role inside it) — `malformed`;
  - nothing before `now` on the repair day changed, and nothing on any other day, except the
    called-out employees' own shifts — `malformed`;
  - called-out employees don't work after `reported_at`; declined/called-out employees aren't in
    the outreach queue — `unavailable`;
  - both schedules through `validate()`, messages prefixed `[schedule_if_…]`; their premium_pay /
    objective include the predictive-scheduling premiums recomputed here, and call-in shifts are not
    charged availability preferences (#16);
  - premiums recomputed from law params only and compared with `FixAction.premium_pay_dollars`
    (summed per employee) and `OutreachCandidate.premium_pay_dollars` (on top of the immediate
    actions); > 2 cents off → `metrics_mismatch` naming the rule and the formula used.
  - The formula and every interpretation are in the `fix.py` docstring (diff of minutes worked per
    employee on the day → added / moved / reduced; grace; < 24 h variants and SF tiers; prorate; caps;
    `scheduled_shift` measure; flat dollars; exemptions incl. group-message, absent-coworker-hours-only,
    text-as-written, SF coworker absence; most expensive rule wins). Never raises (guard → `malformed`).
- Tests (101: 94 fast + 7 slow engine tests, `uv run pytest packages/validator`):
  - A hand-built perfect schedule (TEST-ONLY law values) passes and matches the hand calculation.
  - 25 golden bad schedules, each triggering exactly its code; a test checks every code has one.
  - Fuzz: 200 dict mutations (20% as JSON text) through parse + validate, plus 50 `model_construct`
    garbage shifts. Offline 2000-mutation run after v1.1: 0 guard trips.
  - `tiny_store.json` + `shiftwright_laws.resolve(...)`: WS4's hand schedule passes in TX with
    66 h / $1,276 / 100% coverage; PIT trap, Jordan's Friday unavailability, `not_together` ($25/h)
    are caught; under CA, 8 h shifts need breaks, and 10-min rest breaks at 13:00-13:10 / 17:05-17:15
    satisfy `CA.rest_break.1`. (Under CA, tiny_store's $15–$16 wages also trip `below_minimum_wage`
    against CA's $16.90; that's correct.)
  - `test_fix.py` (24): clean plan; change before now; change on another day; called-out still
    working; declined re-asked; mode mismatch; action missing; #16 preferred_off not charged; TEST-rule
    premium mismatch / schedule metrics / group-offer exemption / extension pricing; garbage plan;
    **a hand-computed premium table for all 10 predictive-scheduling jurisdictions** (Seattle, Chicago,
    Evanston, LA, SF, Berkeley, Emeryville, Philadelphia, NYC, Oregon) × {extension, one-to-one call-in,
    group call-in, 2 h cut}; employer below threshold not covered, None = covered.
  - `test_v11.py`: 5-min breaks pass, 7-min boundary is malformed, off-grid segment edge away from a
    break is malformed, per-minute coverage (1190/1200 = 99.17%, $8.33 gap), school_week
    None/True/False, minimum wage (per employee, unscheduled ignored, future-dated ignored).
- Honors WS3's extra law keys: `rest_break.not_required_under_minutes`,
  `minor_limits.max_hours_non_school_day`, `minor_limits.latest_end_before_non_school_day`.

## Engine audit (black box, main 4f53a85, Fri Nov 6 night)

Harness: `shiftwright_validator.audit` (lazy imports of engine/scenarios/laws; the validator itself
still depends only on contracts) and `uv run python packages/validator/scripts/audit_engine.py
[--time 30] [--seeds 1 2 3] [--json out.json]`. A *disagreement* = a hard violation or a
`metrics_mismatch` in an engine schedule, or an engine status other than optimal/feasible/infeasible.
Not counted as disagreements (listed as "expected"): `below_minimum_wage` (SEMANTICS #15: the engine
never changes wages), and the violations of an empty schedule the engine marked `infeasible`.

Run: `solve_week(time_limit_s=30)` on S × {easy, normal, tight, legal_trap TX, legal_trap CA,
infeasible, messy} × seeds 1–3, plus tiny_store and demo_store, real law packs via
`shiftwright_laws.resolve`. **23 cases, 0 disagreements, 0 metrics_mismatch.** 17 feasible/optimal
schedules all pass every hard check; the claimed metrics match the recompute on every one.
- legal_trap TX 1–3: the planted under-minimum-wage employee (e027 / e021 / e022, $6.25 vs TX
  $7.25) is scheduled and flagged `below_minimum_wage` with `TX.minimum_wage.1`, as #15 says.
  Minors trained on PIT are never put on `pit_operator`.
- infeasible TX 1–3: engine says infeasible, names `c_lod_always`.
- legal_trap CA 1–3: engine says **infeasible** though the scenario expects feasible. See Q1.

Validator-side bugs found: **none**.

### For WS1 (engine)
- **E1 – mislabeled infeasibility.** S/legal_trap/CA (all seeds) returns `status=infeasible` with
  `solver_stats.solver_status = "INFEASIBLE"` (proved), but `infeasibility.summary` says "Could not
  decide within the time limit…", `conflicting_other=["solver_timeout"]` and no constraint/law ids.
  It should say proven infeasible and name `c_lod_always` + the CA meal/rest rules.
  Repro: `solve_week(with_law_pack(generate(1, "S", "legal_trap", "CA").config), time_limit_s=30)`.
- **E2 – short time limits return `error` with no shifts.** `solve_week(S/easy/TX/1, time_limit_s=5)`
  → `status="error"`, 0 shifts, `solver_stats.error="No schedule found within the time limit."`,
  although the greedy stage reported 73 shifts. At 10 s it's feasible. Suggest falling back to the
  greedy schedule when it's valid (I can validate it if you expose it).
- **E3 – time overrun:** 34.9 s on a 30 s limit (S/legal_trap/CA/1).
- **E4 (minor):** infeasible TX: the scenario's expected conflict includes
  `employee:e00N.availability` / `employee:e001.max_hours_week`; the engine only names `c_lod_always`.

### Q1 (DECIDED by David, SEMANTICS #18): a leader on break is NOT on duty; validator unchanged.
Engine and validator agree, but the result surprises: under v1.1 per-minute coverage a leader's break
is a leader gap, so in CA every meal and rest break needs a second leader overlapping.
- tiny_store under CA is provably infeasible (`solve_week` says so in 2 s): 2 leaders, 08:00–20:00. If
  both shifts ≤ 6 h (meal waived) they total exactly 12 h with no overlap, so the rest breaks are
  uncovered. If one is > 6 h its meal must start ≤ 5 h in, so the other leader is present by 13:00 and
  must stay until 20:00 (> 6 h, own meal ≤ 5 h in), which forces the first past 18:30, i.e. > 10 h.
- S/legal_trap/CA: 4 leaders, max 5 days each = 20 leader-days. Without OT (CA daily OT > 8 h) a
  2-leader day can't cover 08:00–22:00 with covered meals, so each day needs ≥ 3 → 21 > 20.
  (Unless a leader works a split shift; the engine's INFEASIBLE proof says no.)
Either (a) keep the semantics and WS4 marks CA legal_trap infeasible / adds a leader, or (b) add to
SEMANTICS that `always_staffed` treats someone on a break as still on duty. Validator change for (b)
is small (count break minutes as covered in `always_staffed` only).

### Regression tests
`tests/test_engine_audit.py` (marked `slow`, ~60 s; skip with `-m "not slow"`): engine on tiny_store
(5 s), S/easy/TX/1 and S/legal_trap/TX/1 (15 s each) → status feasible/optimal, 0 disagreements;
an empty infeasible schedule is not a disagreement; `fix_day` on tiny_store and on the demo store
(Saturday 06:04, e034/e052/e053, modes None and one_to_one) → 0 `validate_fix` disagreements.

## fix_day audit (black box, main 0145de2, Sat Nov 7)

Harness: `shiftwright_validator.audit.audit_fix` / `classify_fix` and
`uv run python packages/validator/scripts/audit_fix.py [--time 20] [--seeds 1 2 3] [--all-fww]`.
Disagreement = any hard `validate_fix` violation or `metrics_mismatch`, except `below_minimum_wage`.

- **TX (no predictive-scheduling rules): clean.** Demo store Saturday 06:04 e034/e052/e053 and
  S easy/normal/tight/messy TX × seeds 1–3 via `pick_callouts` (12 plans): **0 disagreements** for
  mode None / one_to_one. Nothing before `now` changed, call-outs removed, actions match the schedule,
  both schedules pass `validate()` and their metrics match.
- **Demo store moved into each of the 10 predictive-scheduling jurisdictions × 3 modes (30 plans):**
  0 structural disagreements; all disagreements are premiums / mode (374 total over the 33 demo runs,
  incl. TX). "Expected" `below_minimum_wage` hits are the Austin demo wages under city minimums
  (relocation artefact, not a finding).

### For WS1 (engine) — fix_day
- **F1 – premiums missing in 6 of 10 jurisdictions.** Seattle, Chicago, Evanston, LA, Philadelphia,
  Oregon: every extension and call-in has `premium_pay_dollars = 0`, no `law_rule_ids`, no rationale
  note, also with `Store.employer_employee_count = 1000`. Per #17 they're due, e.g. Seattle e030
  extended 30 min: 0.5 h × $17.25 = $8.63 (prorate); Philadelphia e035 +3 h: 1 h × $21. Only
  Berkeley / Emeryville / SF extensions are priced (and Berkeley/Emeryville match the validator exactly).
- **F2 – call-ins never priced.** Every `OutreachCandidate.premium_pay_dollars = 0` with empty
  `law_rule_ids` / `premium_note`, including Berkeley/Emeryville/Evanston/Oregon where no exemption
  applies (`voluntary_additional_hours_exempt: false`, or OR texts aren't written consent), and
  one-to-one texts in Seattle/Philadelphia (exemption needs a group message).
- **F3 – `outreach_mode` ignored.** `FixRequest.outreach_mode="group_offer"` → `FixPlan.outreach_mode
  = "one_to_one"` in every jurisdiction (TX included); None never picks group_offer even where it's
  the cheaper legal mode (Seattle, Philadelphia).
- **F4 – schedule metrics leave premiums out.** Berkeley: actions carry $158.50 of premiums but
  `schedule_if_none_accept.metrics.premium_pay_dollars = 0` (#17 says they're included); so
  premium_pay and objective mismatch.
- **F5 – SF details (needs WS3 to confirm the reading):** the engine charges 1 h for < 24 h changes;
  WS3's `under_24h_tiers` gives 2 h for ≤ 4 changed hours. The engine also charges extensions
  that cover an absent coworker's hours, which `coworker_absence_exempt` exempts.
- Repro: `audit_fix.py --all-fww` (≈ 6 min), or one place:
  `load_demo_store()`, set `store.jurisdiction = Jurisdiction(state="WA", city="seattle")`,
  `law_pack = resolve(...)`, `solve_week(30 s)`, `fix_day(FixRequest(..., day=5, now=364,
  callouts=e034/e052/e053 @364))`, then `validate_fix(req, plan)`.

### For WS4 (scenarios)
- Demo call-outs are reported at 06:04 for shifts that started 04:00 (e034, e052). `validate_fix`
  treats the called-out employee's whole shift as gone, so it doesn't flag the change before `now`;
  real call-outs would come before the shift.

**In progress:** nothing.

**Next slice:** re-run `audit_fix.py --all-fww` after WS1 fixes F1–F4; get WS3/David to confirm the
SF reading (F5) and how NYC prohibitions should be reported (needs a ViolationCode → contracts request);
add `validate_fix` to WS5 evals and to the API readiness check if wanted.

**Blocked on:** nothing.

**Shortcuts taken:**
- Not checked (SEMANTICS #14): `week_stability`, reporting-time pay; predictive-scheduling premiums
  only inside `validate_fix` (a weekly `validate()` has no posted schedule to diff against).
- `validate_fix` premium shortcuts: stores are assumed retail (`applies_to: food` rules skipped);
  `min_locations`, `min_covered_employees`, `min_local_employees`, city count scopes and
  `covered_salary_max_annual` assumed met (no data); `post_deadline_grace_hours`,
  `moved_premium_per_attribute` (a same-day fix only changes time → ×1), `standby_list_first` and
  `exemption_individual_ok_if_on_shift` (extensions here aren't consented) not modelled; NYC's
  prohibitions (`cancel_or_reduce_prohibited_within_notice`, written consent) are not yet reported
  as violations (no ViolationCode fits; would need a contracts request). "Notice" = shift start − now.
- `metrics_mismatch` is skipped when the schedule has no `metrics`.
- `store_id` mismatch → `unknown_entity`; `week_start` mismatch → `malformed`. `config_version` isn't checked.
- Rest-between-shifts compares each shift to the employee's previous one, so split shifts on the same day
  count. Overlapping shifts count as `double_booked`, not as a rest problem.
