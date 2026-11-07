# WS2 status — validator

Contracts: **v1.1** (`contracts/SEMANTICS.md`). The validator follows it item by item.

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
- Tests (75: 70 fast + 5 slow engine tests, `uv run pytest packages/validator`):
  - A hand-built perfect schedule (TEST-ONLY law values) passes and matches the hand calculation.
  - 25 golden bad schedules, each triggering exactly its code; a test checks every code has one.
  - Fuzz: 200 dict mutations (20% as JSON text) through parse + validate, plus 50 `model_construct`
    garbage shifts. Offline 2000-mutation run after v1.1: 0 guard trips.
  - `tiny_store.json` + `shiftwright_laws.resolve(...)`: WS4's hand schedule passes in TX with
    66 h / $1,276 / 100% coverage; PIT trap, Jordan's Friday unavailability, `not_together` ($25/h)
    are caught; under CA, 8 h shifts need breaks, and 10-min rest breaks at 13:00-13:10 / 17:05-17:15
    satisfy `CA.rest_break.1`. (Under CA, tiny_store's $15–$16 wages also trip `below_minimum_wage`
    against CA's $16.90; that's correct.)
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

### Q1 for David / WS4: is a leader on break "on duty" for `always_staffed`?
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
`tests/test_engine_audit.py` (marked `slow`, ~30 s; skip with `-m "not slow"`): engine on tiny_store
(5 s), S/easy/TX/1 and S/legal_trap/TX/1 (15 s each) → status feasible/optimal, 0 disagreements;
an empty infeasible schedule is not a disagreement; `fix_day` plans (`schedule_if_all_accept` /
`schedule_if_none_accept` via `audit_fix_plan`) — **skips until `shiftwright_engine.fix_day` exists**.

**In progress:** nothing.

**Next slice:** when `fix_day` lands, the skipped test runs on tiny_store; extend the audit script to
call `fix_day` on each feasible S schedule with `pick_callouts(...)` and check both plan schedules
plus SEMANTICS #16 (call-ins not charged preferred_off/on; ranking). Re-run the audit after any
engine change; resolve Q1.

**Blocked on:** nothing.

**Shortcuts taken:**
- Not checked (SEMANTICS #14): `week_stability`, predictive-scheduling premiums, reporting-time pay.
- `metrics_mismatch` is skipped when the schedule has no `metrics`.
- `store_id` mismatch → `unknown_entity`; `week_start` mismatch → `malformed`. `config_version` isn't checked.
- Rest-between-shifts compares each shift to the employee's previous one, so split shifts on the same day
  count. Overlapping shifts count as `double_booked`, not as a rest problem.
