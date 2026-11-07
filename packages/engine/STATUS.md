# WS1 status

**Done (M1):**
- `solve_week(config, time_limit_s=20, previous=None)` — CP-SAT, two phases:
  1. choose shifts (one bool per candidate (start, length) per employee-day) + per-slot role
     assignment + priced gaps + hard/soft rules;
  2. shifts fixed, roles re-assigned with a $0.50/segment churn tiebreak (not in reported objective).
- `explain_gap(config, schedule, gap)` — one `GapReason` per employee trained for the role, from
  config + schedule only. Also filled into every gap by `solve_week`.
- `find_conflicts(config)` — hard-only model with one assumption literal per hard `Constraint`, law
  rule, `employee:<id>.max_hours_week`, `budget.weekly_hours_cap`, `budget.weekly_dollar_cap`; maps
  `sufficient_assumptions_for_infeasibility()` to `Infeasibility`. `solve_week` calls it on INFEASIBLE.
- Acceptance tests (tiny store, hand-made, fake test law): optimal < 2 s (actual ~0.2 s), no-trained
  gaps with full penalty and empty reasons, one reason per trained cashier, minor never on PIT,
  10 h budget cap, approvals raise the cap, contradictory hard set → infeasible with the id,
  provisional rules ignored. `tests/selfcheck.py` is a small independent hard-rule checker used
  until WS2's validator lands.

**In progress:**
- Demo-scale performance. Synthetic 60-staff/7-day store (`engine_fixtures.demo_like_store`):
  92k candidate shifts; 30 s gives ~10% gap, 90 s ~3.5%. Target is <30 s with ≤1% gap. Working on it.
- `fix_day` (M2) — not implemented yet (raises ImportError if called).

**Blocked on:**
- Nothing. Switch tests to `packages/scenarios/fixtures/tiny_store.json` when WS4 lands it.

**Interpretations / shortcuts (please review — validator WS2 should agree):**
- Hours = paid hours: shift length minus unpaid breaks. Budget hours and `max_hours_week` use paid hours.
- Breaks are deterministic per (start, length):
  - meal: if length > `after_minutes` (strict). Starts at `latest_start_minute_of_shift` (snapped
    down to the slot grid) or at the midpoint if null. One meal per shift (no second-meal tier).
    `waivable_under_minutes` is ignored (we never assume a waiver).
  - rest: `floor(length / per_minutes_worked)` breaks, evenly spaced.
  - Break durations are rounded UP to the slot size (contract requires slot-aligned times), e.g. a
    10-min rest break becomes 30 min at 30-min slots.
  - If several meal/rest rules exist, the one with the smallest threshold is used.
- Law `min_rest_between_shifts` is enforced as a hard ban (the engine never pays the premium).
- `minor_limits`: all rules whose age range matches apply (school-week and non-school rules both →
  most restrictive). `latest_end_summer` unused.
- `minor_prohibited_roles` and `Role.min_age` block the role; reason code `minor_rule`.
- Overtime: if `overtime_allowed=False`, weekly paid hours ≤ weekly OT threshold and shift paid hours
  ≤ daily OT threshold. If allowed, premium = (multiplier−1)×wage per OT hour, daily and weekly
  both counted (may pyramid; conservative).
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
