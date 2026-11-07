# Shiftwright contract semantics — v1.1

Owner: David. These rules are part of the contract. The engine (WS1) and the validator (WS2)
must both follow them, so that a disagreement means a bug, not a different reading.
Accepted from `contracts/requests/ws2-validator-semantics.md` (items 1–14) on Fri Nov 6, 22:30 CT,
with the v1.1 changes below folded in.

## Changelog

- **1.1.0** (Fri Nov 6):
  - `FixPlan.plan_id: Optional[str]` (WS6 request). The engine leaves it `None`; the API fills it.
  - Breaks off the slot grid (WS1 request): `Break.start/end`, and `RoleSegment.start/end` where
    they touch a break, are multiples of `BREAK_GRANULARITY_MINUTES` (5). Everything else stays on
    `Store.slot_minutes`. Coverage and gap penalties are measured per minute.
  - `Store.school_week: Optional[bool]` (WS2 suggestion; see #8).
  - `ViolationCode.below_minimum_wage` (WS2 suggestion; see #15).
  - This file (WS2 semantics, accepted as written apart from the edits marked *v1.1*).
- **1.0.0**: initial contracts.

## Metrics

1. **`coverage_pct` is 0–100**, not 0–1.
   Coverage = covered headcount-minutes / required headcount-minutes. At each minute, covered =
   min(demand for the role at that minute, people working that role then). *v1.1: measured per
   minute, so short off-grid breaks reduce coverage only by their real length.*
2. **`total_wage_cost` includes the overtime premium** (the extra 0.5× part). `premium_pay_dollars`
   covers only law premiums such as rest-window (clopen) pay.
3. **Paid hours = clock span − unpaid breaks.** Paid breaks count toward hours, cost, budget, OT and
   `max_hours_week`. Each break's own `paid` flag is used.
4. **Overtime** comes only from law-pack `daily_overtime` / `weekly_overtime` (no pack = no OT).
   Daily OT hours are removed before the weekly threshold applies, so no hour counts twice. Hours
   above `double_threshold_hours` are paid 2×. A shift's hours count on the day it starts.
5. **Shift length** (min/max_shift_length) and break triggers use the clock span, breaks included.
13. **`metrics_mismatch`** fires when a claimed field differs from the recomputed value by more than
    1% *and* more than an absolute floor ($1, 0.1 h, or 1 coverage point). Engine-only tiebreak
    penalties (e.g. role churn) must stay out of the reported metrics.
    *v1.1:* gap penalty = Σ missing headcount-minutes / 60 × `Role.gap_penalty_per_hour`.

## Breaks

6. **Rest breaks needed** = floor(span / `per_minutes_worked`). With WS3's
   `not_required_under_minutes`, at least 1 is needed at or above that length. A break at least as
   long as the required `duration` satisfies it. *v1.1: with 5-minute break granularity, a 10-minute
   rest break can be exactly 10 minutes.*
7. **Meal breaks:** each `meal_break` rule with span > `after_minutes` requires one more meal break
   of at least `duration`. A shift ≤ `waivable_under_minutes` is treated as waived. The k-th meal
   must start ≤ `latest_start_minute_of_shift` minutes into the shift.

## Minors

8. **Minor limits** are applied by `Store.school_week` (*v1.1*):
   - `None` (unknown, the default): every matching `minor_limits` rule is enforced, school-week rules
     included (strictest; this is the v1.0 behaviour). Mon–Fri count as school days.
   - `True`: only rules with `school_week: true`. Mon–Fri are school days.
   - `False`: only rules with `school_week: false`; no day is a school day.
   `minor_prohibited_roles` and `Role.min_age` always apply.

## Rules and budget

9. **`min_rest_between_shifts` law rule with `premium_multiplier`** is priced, not a violation:
   hours of the later shift inside the rest window × wage × (multiplier − 1), in
   `premium_pay_dollars`. Without a multiplier it is a hard `rest_between_shifts` violation.
10. **`budget_dollars`** compares `total_wage_cost + premium_pay_dollars` to the cap + approvals'
    `extra_dollars`.
11. **Soft units** for kinds without one: shift length = $/hour short or over; rest = $/hour
    missing; days and consecutive days = $/extra day; always_staffed = $/uncovered hour.
12. **Soft-family kinds marked `hard`** (`min_hours_week`, `not_together`, `fair_spread`,
    `preferred_role`) are enforced and reported with code `soft`, severity `hard`.
14. **Not checked by the validator** (it isn't given the data): `week_stability`,
    predictive-scheduling change premiums, reporting-time pay.

## Minimum wage (*v1.1*)

15. **`below_minimum_wage`** (hard): for every employee with at least one shift, if
    `wage_per_hour` < the law pack's `minimum_wage.dollars_per_hour` (the rule in effect on
    `Store.week_start`), the validator reports one violation per employee with that `law_rule_id`.
    The engine never changes wages: it schedules as normal, and the API's readiness report shows a
    failing "wages ≥ minimum wage" check naming the employees.
