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
- Tests (70, `uv run pytest packages/validator`):
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

**In progress:** nothing.

**Next slice (once WS1's engine is on main):** run every engine schedule on the S scenarios
(`packages/scenarios`) through `validate()`, and file every disagreement (engine says feasible but the
validator finds a hard violation, or the metrics differ beyond the SEMANTICS #13 tolerance) here and
to the coordinator with a minimal repro. Don't read engine code to do it; use only its outputs.

**Blocked on:** nothing.

**Shortcuts taken:**
- Not checked (SEMANTICS #14): `week_stability`, predictive-scheduling premiums, reporting-time pay.
- `metrics_mismatch` is skipped when the schedule has no `metrics`.
- `store_id` mismatch → `unknown_entity`; `week_start` mismatch → `malformed`. `config_version` isn't checked.
- Rest-between-shifts compares each shift to the employee's previous one, so split shifts on the same day
  count. Overlapping shifts count as `double_booked`, not as a rest problem.
