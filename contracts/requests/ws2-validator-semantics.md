# WS2 request: confirm metric and rule semantics the contracts leave open

**From:** WS2 (validator) · **Blocking?** No. The validator ships with the readings below. If the
engine reads any of them differently, `metrics_mismatch` or a hard violation will show up on
engine schedules, so it's worth confirming before the engine lands.

Where the contract is silent, the validator currently does this:

1. **`coverage_pct` is 0–100**, not 0–1. (SPEC demo text says "71% → 96%".)
2. **`total_wage_cost` includes the overtime premium** (the extra 0.5× part). `objective_dollars`
   has no separate OT term, so OT has to live in either wages or premiums. `premium_pay_dollars`
   covers only law premiums such as rest-window (clopen) pay.
3. **Paid hours = clock span − unpaid breaks.** Paid breaks count toward hours, cost, budget, OT,
   and `max_hours_week`. The break's own `paid` flag is used.
4. **Overtime:** only from law-pack `daily_overtime` / `weekly_overtime` (no pack means no OT).
   Daily OT hours are removed before the weekly threshold applies, so no hour counts twice. Hours above
   `double_threshold_hours` are paid 2×. A shift's hours count on the day it starts.
5. **Shift length** (min/max_shift_length) and break triggers use the clock span, breaks included.
6. **Rest breaks needed** = floor(span / `per_minutes_worked`). With WS3's
   `not_required_under_minutes`, at least 1 is needed at or above that length. A longer break
   (e.g. 30 min on a 30-min grid) satisfies a 10-min requirement. *"Major fraction" rounding can't be
   expressed in the params; consider adding a param if WS3 thinks the data needs it.*
7. **Meal breaks:** each `meal_break` rule with span > `after_minutes` requires one more meal break of at
   least `duration`. A shift ≤ `waivable_under_minutes` is treated as waived. The k-th meal must start
   ≤ `latest_start_minute_of_shift` minutes into the shift.
8. **Minor limits:** every matching rule is enforced (WS3: "stacked"), school-week rules included,
   because nothing says whether the week is a school week. Mon–Fri count as school days.
   **Suggested contract addition:** `Store.school_week: bool | None` (and maybe `summer: bool`).
9. **`min_rest_between_shifts` law rule with `premium_multiplier`** is priced, not a violation:
   hours of the later shift inside the rest window × wage × (multiplier − 1), in `premium_pay_dollars`.
   Without a multiplier it is a hard `rest_between_shifts` violation.
10. **`budget_dollars`** compares `total_wage_cost + premium_pay_dollars` to cap + approvals' `extra_dollars`.
11. **Soft units** for kinds without one in the contract: shift length is $/hour short or over,
    rest is $/hour missing, days and consecutive days are $/extra day, always_staffed is $/uncovered hour.
12. **Soft-family kinds marked `hard`** (`min_hours_week`, `not_together`, `fair_spread`,
    `preferred_role`) are enforced and reported with code `soft`, severity `hard`. There's no
    dedicated `ViolationCode` for them.
13. **`metrics_mismatch`** fires when a claimed field differs from the recomputed value by more than 1%
    *and* by more than an absolute floor ($1, 0.1 h, or 1 coverage point). Any engine-only
    tiebreak penalty (e.g. role churn) that is folded into `soft_penalty_dollars`/`objective_dollars` would
    show up here. Suggest keeping such tiebreaks out of the reported metrics.
14. **Not checked (needs data `validate()` isn't given):** `week_stability`, predictive-scheduling
    change premiums, reporting-time pay, minimum wage (an employee wage below `minimum_wage`: easy to add
    as a hard check if you want it; there's no ViolationCode for it today).


---
**Decision (David, Fri Nov 6 22:30 CT): ACCEPTED in contracts v1.1.** See `contracts/SEMANTICS.md`.
