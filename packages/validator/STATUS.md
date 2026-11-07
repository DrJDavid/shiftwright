# WS2 status — validator

Contracts: **v1.5** (`contracts/SEMANTICS.md`). The validator follows it item by item
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
- v1.5 slice (implemented from SEMANTICS only):
  - **#23 split shifts:** `shifts_per_day` (hard) when an employee has more shifts on a day (by start
    day) than `Store.max_shifts_per_day`. Length, breaks and tiling are per shift; daily OT, minor caps
    and days worked already sum or count by day. The store `min_rest_between_shifts` constraint (hard and
    soft) only spans different days. Law `min_rest_between_shifts` (hard, or priced via premium) spans
    every consecutive pair unless `excludes_same_day_split: true`.
  - **#20 tipped pay:** a shift whose every segment is a `tipped` role pays `tipped_wage_per_hour` if
    the employee has one (`common.shift_wage`); mixed shifts pay `wage_per_hour`; OT premium always on
    `wage_per_hour`. (Law premiums in `validate_fix` also use `wage_per_hour`.)
  - **#15 tipped minimum:** employees with ≥1 tipped shift also have `tipped_wage_per_hour` checked
    against the in-effect `tipped_minimum_wage.cash_wage_per_hour` (same "in effect" logic as
    `minimum_wage`), or against the full `minimum_wage` if the pack has no tipped rule. Separate
    violation, message says which floor applied.
  - **#21:** a `role_tags` value outside `ROLE_TAGS` is `malformed`; `minor_prohibited_roles` honours
    `age_min <= age < age_below`.
  - **#19 sector:** `common.law_rules()` drops rules whose `applies_to` doesn't match `Store.sector`
    (`both`, or sector None/other ⇒ applies; lists accepted). Every check and `validate_fix` inherit it;
    the old "stores are retail" assumption in `validate_fix` is gone.
- Tests (133: 122 fast + 11 slow engine tests, `uv run pytest packages/validator`):
  - A hand-built perfect schedule (TEST-ONLY law values) passes and matches the hand calculation.
  - 29 golden bad schedules, each triggering exactly its code; a test checks every code has one.
    v1.5 goldens: split shift beyond the max (`shifts_per_day`), unknown role tag (`malformed`),
    tipped underpayment (`below_minimum_wage`), 15-year-old on a fryer role (`minor_prohibited_role`).
    `golden_rest` now spans two days (the store constraint no longer applies within a day).
  - Fuzz: 200 dict mutations (20% as JSON text) through parse + validate, plus 50 `model_construct`
    garbage shifts. Offline 2000-mutation run after v1.1: 0 guard trips.
  - `tiny_store.json` + `shiftwright_laws.resolve(...)`: WS4's hand schedule passes in TX with
    66 h / $1,276 / 100% coverage; PIT trap, Jordan's Friday unavailability, `not_together` ($25/h)
    are caught; under CA, 8 h shifts need breaks, and 10-min rest breaks at 13:00-13:10 / 17:05-17:15
    satisfy `CA.rest_break.1`. (Under CA, tiny_store's $15–$16 wages also trip `below_minimum_wage`
    against CA's $16.90; that's correct.)
  - `test_fix.py` (26): clean plan; unexplained change; plain validate() with unverified premium; change before now; change on another day; called-out still
    working; declined re-asked; mode mismatch; action missing; #16 preferred_off not charged; TEST-rule
    premium mismatch / schedule metrics / group-offer exemption / extension pricing; garbage plan;
    **a hand-computed premium table for all 10 predictive-scheduling jurisdictions** (Seattle, Chicago,
    Evanston, LA, SF, Berkeley, Emeryville, Philadelphia, NYC, Oregon) × {extension, one-to-one call-in,
    group call-in, 2 h cut}; employer below threshold not covered, None = covered.
  - `test_v15.py` (22): split shift allowed at 2, three shifts at max 2, each split measured alone,
    minor daily cap sums splits, law rest spans splits unless excluded, tipped cost / mixed shift / OT on
    full wage, no tip-credit rule → full minimum, tipped wage ignored without a tipped shift, known tags,
    age_min both ways, 7 sector cases, no applies_to = everywhere.
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
`tests/test_engine_audit.py` (marked `slow`, ~100 s; skip with `-m "not slow"`): engine on tiny_store
(5 s), S/easy/TX/1 and S/legal_trap/TX/1 (15 s each) → status feasible/optimal, 0 disagreements;
an empty infeasible schedule is not a disagreement; `fix_day` on tiny_store, and on the Austin and
Chicago demo stores (Saturday 06:04, e034/e052/e053) × 3 modes → 0 `validate_fix` disagreements and
the plan uses the requested mode.

## fix_day audit (black box, main fb4dadf + d73494b, Sat Nov 7; engine ab46904)

Harness: `shiftwright_validator.audit.audit_fix` / `classify_fix`, and
`uv run python packages/validator/scripts/audit_fix.py [--time 20] [--seeds 1 2 3] [--all-fww]`
(about 8 min with `--all-fww`). Disagreement = any hard `validate_fix` violation or `metrics_mismatch`,
except `below_minimum_wage`.

Run: demo stores Austin / Chicago / Seattle / SF (`load_demo_store(locality)`), Saturday 06:04,
e034/e052/e053 call out, × modes None / one_to_one / group_offer; the Austin store moved into all
10 predictive-scheduling jurisdictions × 3 modes; S easy/normal/tight/messy TX × seeds 1–3 via
`pick_callouts`. **54 plans, 40 clean, 54 disagreements in the other 14** (Seattle, SF, Oregon only).
No plan changes anything before `now`, keeps a called-out employee working, or re-asks a decliner.
"Expected" `below_minimum_wage` hits only come from moving the Austin store's wages into other cities.

Clean: Austin, Chicago (native and moved), Evanston, LA, Berkeley, Emeryville, Philadelphia, NYC,
all 12 S plans, and Seattle native one_to_one. WS1's ab46904 fixed the earlier F1–F4 (missing
premiums, unpriced call-ins, ignored outreach_mode, metrics without premiums).

### For WS1 (engine) — remaining (repro: `audit_fix.py --all-fww`, or `load_demo_store("seattle"|"sf")`)
- **G1 – changes only in schedule_if_all_accept, not named or priced.** e.g. Seattle (moved): e058
  11:30→11:00 and (native) e011 12:00→12:30 appear only in `schedule_if_all_accept`, with no action
  and no candidate, so no premium, and `metrics.premium_pay_dollars` is off by that amount (e.g.
  $146.00 claimed vs $158.13). Now caught as `malformed` "hours change … but no action or outreach
  candidate names them".
- **G2 – grace minutes.** WS3: changes *shorter than* `grace_minutes` are free. Oregon (30):
  30-minute extensions (e035, e045) get $0 with "change under 30 min"; validator charges 1 h × wage.
  Seattle (15): e011's 30-minute extension gets $0 with "change under 15 min"; validator charges
  0.5 h × $17.75 = $8.88 (prorate).
- **G3 – Seattle group_offer, `exemption_only_for_absent_coworker_hours`.** e039 called in 11:00–18:30;
  the called-out coworkers' hours end at 18:00, so 30 min aren't covering an absence: validator charges
  0.5 h × wage (prorate); engine exempts the whole shift.
- **G4 – SF `coworker_absence_exempt` on extensions.** e038 extended 09:00–11:00 inside the absent
  coworkers' hours (06:04–16:30): engine charges $42.50 (2 h tier); validator exempts it (WS3: covering
  an absent coworker "is exempt even without consent"). The engine already exempts SF call-ins this way.
  **WS3 please confirm** the key also covers extensions.

### Q2 for David — are `actions` part of schedule_if_all_accept?
The engine's all_accept schedule often drops the immediate extensions (e.g. Berkeley e007, e016, e029,
e044 are extended in none_accept but not in all_accept) and prices only what's left. The contract calls
actions "immediate … no consent needed", which reads as "in both schedules". The validator accepts either
(it prices whatever each schedule contains) but G1 is the unpriced version of this.

### validate() vs predictive-scheduling premiums (WS1 report)
`validate()` has no posted schedule, so it can't recompute #17 premiums. Chosen fix (no contract
change): when the law pack has `predictive_scheduling` rules, plain `validate()` accepts a claimed
`premium_pay_dollars` at or above its own clopen premium and compares `objective_dollars` after adding
that unverified amount back. A claimed premium below the recomputed clopen premium still fails.
`validate_fix` sets `ctx.premiums_exact = True` after adding its own #17 premiums, so plan schedules are
checked exactly. Callers that have the FixRequest/FixPlan should use `validate_fix`. Test:
`test_plain_validate_accepts_unverified_fww_premium`.

### For WS4 (scenarios)
- Demo call-outs are reported at 06:04 for shifts that started at 04:00 (e034, e052). `validate_fix`
  treats a called-out employee's whole shift as gone, so it doesn't flag the change before `now`.

## Grok's S/legal_trap/CA schedule (WS5 run real-quick-1, read-only)
`baseline_x-ai__grok-4.7/weekly-S-legal_trap-CA-s1/schedule.json` with its `_inputs` config:
- Recorded validation (pre-v1.5 validator): passed, 0 hard.
- Now, `max_shifts_per_day = 1` (the config as recorded): **1 hard, `shifts_per_day`**. Leader e002
  works Sun 08:00–12:00 and 18:00–22:00, each with a 10-min rest break covered by another leader.
- With `max_shifts_per_day = 2` (WS4's planned setting): **passes, 0 hard** (591.5 h, 90.68% coverage,
  objective $15,671.75). So S/legal_trap/CA is feasible once split shifts are allowed, which is the
  split-shift loophole in my Q1 note. The engine's earlier INFEASIBLE was correct at 1 shift/day. Re-run
  `solve_week` there once WS4 sets 2: the engine should then find a schedule too (#23: an infeasibility
  proof must hold for the store's max).

**In progress:** nothing.

**Next slice:** re-run the engine audit (`audit_engine.py`) on S legal_trap CA once WS4 sets
`max_shifts_per_day=2`; re-run `audit_fix.py --all-fww` after WS1 handles G1–G3 (and G4 once WS3 confirms);
David to answer Q2; NYC prohibitions need a ViolationCode (contracts request) before the validator can
report them; offer `validate_fix` to WS5 evals and to the API readiness check.

**Blocked on:** nothing.

**Shortcuts taken:**
- Not checked (SEMANTICS #14): `week_stability`, reporting-time pay; predictive-scheduling premiums
  only inside `validate_fix` (a weekly `validate()` has no posted schedule to diff against).
- `validate_fix` premium shortcuts: `min_locations`, `min_covered_employees`, `min_local_employees`, city count scopes and
  `covered_salary_max_annual` assumed met (no data); `post_deadline_grace_hours`,
  `moved_premium_per_attribute` (a same-day fix only changes time → ×1), `standby_list_first` and
  `exemption_individual_ok_if_on_shift` (extensions here aren't consented) not modelled; NYC's
  prohibitions (`cancel_or_reduce_prohibited_within_notice`, written consent) are not yet reported
  as violations (no ViolationCode fits; would need a contracts request). "Notice" = shift start − now.
- `metrics_mismatch` is skipped when the schedule has no `metrics`.
- `store_id` mismatch → `unknown_entity`; `week_start` mismatch → `malformed`. `config_version` isn't checked.
- Rest-between-shifts compares each shift to the employee's previous one, so split shifts on the same day
  count. Overlapping shifts count as `double_booked`, not as a rest problem.
