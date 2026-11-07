# WS2 status — validator

**Done (M1 target met):**
- `validate(config, schedule) -> ValidationReport`, `parse_schedule_lenient(raw)`,
  `recompute_metrics(config, schedule)`, plus `validate_raw(config, raw)` (parse + validate in one
  call, parse problems included; meant for WS5 baseline outputs).
- One check function per `ViolationCode` (`checks.py`, `ALL_CHECKS`), plain loops. Constraint
  measurements are shared by hard checks and soft pricing (`measure.py`). Only `confirmed`
  constraints count.
- Never crashes. Shifts with insane fields are reported `malformed` and skipped by the other checks.
  Each check runs inside a guard that turns an unexpected exception into a hard `malformed`
  violation, and the fuzz tests fail if that guard ever fires.
- Tests (53, `uv run pytest packages/validator`):
  - A hand-built perfect schedule (TEST-ONLY law values) passes and matches the hand calculation.
  - 24 golden bad schedules, each triggering exactly its code; a test checks every code has one.
  - Fuzz: 200 dict mutations (20% as JSON text) through parse + validate, plus 50 `model_construct`
    garbage shifts. 2000-mutation offline run: 0 guard trips.
  - `tiny_store.json` + `shiftwright_laws.resolve("TX")`: WS4's hand schedule passes with
    66 h / $1,276 / 100% coverage. PIT trap (minor on forklift → `US.minor_prohibited_roles.1`),
    Jordan's Friday unavailability, and Casey/Jordan `not_together` ($25/h) are all caught. Under CA
    the 8 h shifts need meal and rest breaks.
- Honors WS3's extra law keys: `rest_break.not_required_under_minutes`,
  `minor_limits.max_hours_non_school_day`, `minor_limits.latest_end_before_non_school_day`.

**Interpretations (need David's confirmation):** see `contracts/requests/ws2-validator-semantics.md`.
In short: coverage is 0–100; the OT premium sits inside `total_wage_cost`; paid breaks count as hours;
OT comes from the law pack only; all minor rules are stacked (school week assumed); clopen premium
is priced, not a violation.

**In progress:** nothing. Next: once WS1 lands, run every engine schedule on the S scenarios and file
any disagreements here.

**Blocked on:** nothing.

**Shortcuts taken:**
- Not checked: `week_stability`, predictive-scheduling premiums, reporting-time pay, and minimum
  wage. `validate()` lacks the data for the first three; there's no ViolationCode for the last.
- `metrics_mismatch` is skipped when the schedule has no `metrics`.
- `store_id` mismatch → `unknown_entity`; `week_start` mismatch → `malformed`. `config_version` isn't checked.
- Rest-between-shifts compares each shift to the employee's previous one, so split shifts on the same day
  count. Overlapping shifts count as `double_booked`, not as a rest problem.
