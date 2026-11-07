# Shiftwright contract semantics — v1.4

Owner: David. These rules are part of the contract. The engine (WS1) and the validator (WS2)
must both follow them, so that a disagreement means a bug, not a different reading.
Accepted from `contracts/requests/ws2-validator-semantics.md` (items 1–14) on Fri Nov 6, 22:30 CT,
with the v1.1 changes below folded in.

## Changelog

- **1.4.0** (Sat Nov 7, ~02:30): outreach modes for predictive-scheduling exemptions (#17, proposal from WS1):
  `FixRequest.outreach_mode`, `FixPlan.outreach_mode`, `OutreachCandidate.premium_pay_dollars`,
  `law_rule_ids`, `premium_note`. Decision (David): `always_staffed` is NOT satisfied by an employee on a
  break (#18).
- **1.3.0** (Sat Nov 7, ~01:30): predictive-scheduling premiums in call-out repair (#17);
  `Store.employer_employee_count`, `Store.schedule_posted_on`; new `predictive_scheduling` param keys
  that WS3 fills from primary sources (#17). No other schema change.
- **1.2.0** (Sat Nov 7, ~01:00):
  - `Shift.why: list[str]` — engine-generated, factual reasons for each assignment (headline first).
    Must only state facts derivable from the config and the schedule. The validator ignores it.
  - API.md: `demo` / `tiny` templates, `ImportPreview.target_fields` / `required_fields`,
    `MOCK_AUTOREPLY` / `MOCK_REPLY_DELAY_S` / `MOCK_SEED`, question auto-answer, card supersede.
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

## Call-out repair (*v1.1, accepted Sat Nov 7 00:30 from `requests/ws4-callin-preferred-off.md`*)

16. **A `call_in` is not charged the employee's `preferred_off` / `preferred_on` weights.** A call-in
    needs the employee's consent by text, so the preference is respected when they answer.
    Outreach ranking = coverage gained per added dollar × `est_accept_prob`, where
    `est_accept_prob = (callins_accepted_90d + 1) / (callins_offered_90d + 2)`.

## Predictive scheduling in call-out repair (*v1.3*)

17. When the store's law pack has `predictive_scheduling` rules (city or state Fair Workweek laws),
    `fix_day` prices every change to the posted schedule:
    - **Applies** only if `Store.employer_employee_count` is None or exceeds `applies_if_employees_over`
      (null threshold = always), and the change happens inside the rule's notice window
      (`notice_days` before the shift; the posted schedule is `FixRequest.schedule`, assumed posted on
      time unless `Store.schedule_posted_on` says otherwise).
    - **Kinds of change** (per affected employee and shift): *added hours / new shift*, *shift moved or
      extended*, *hours reduced or shift cancelled*. The employee who called out is never charged: an
      employee-initiated absence is not an employer change.
    - **Amount** comes only from the rule's params (WS3 encodes them with citations; examples of keys:
      `change_premium_hours`, `change_premium_hours_under_24h`, `reduced_hours_fraction`,
      `premium_multiplier`, `premium_flat_dollars`). If a param the formula needs is missing, the
      engine charges nothing for that rule and adds a `FixAction.rationale` note "premium not
      computed: <rule id> lacks <param>" — never a guessed amount.
    - **Exemptions** come only from params: `voluntary_additional_hours_exempt: bool` (true when the
      ordinance exempts extra hours an employee accepts voluntarily), `consent_must_be_written: bool`,
      and `exemption_note: str` (what the consent must look like, quoted from the source). A `call_in`
      accepted by text counts as voluntary and written consent when both flags say so; the outreach
      message then states that accepting is voluntary. Absent flags ⇒ not exempt (charge the premium).
    - **Output:** each `FixAction.premium_pay_dollars` / `OutreachCandidate.added_cost_dollars`
      includes the premium; `FixAction.law_rule_ids` names the rule; the rationale says why
      ("Chicago predictability pay: +1 h at $17.50 (shift extended < 14 days' notice)" or
      "No predictability pay: voluntary call-in accepted in writing, exempt under <rule id>").
      `schedule_if_*_accept.metrics.premium_pay_dollars` include these premiums.
    - The validator checks this via a fix-plan check that recomputes premiums from the same params
      (WS2), not by reading engine code.

    - *v1.4 outreach modes:* `one_to_one` texts candidates in rank order; `group_offer` sends one written
      message to the top N (N ≥ the rule's `exemption_min_recipients`) carrying every statement in
      `exemption_message_must_state`; first accept wins. The engine prices call-ins for the mode in
      `FixRequest.outreach_mode`, or picks the cheaper legal mode when it is None, and reports it in
      `FixPlan.outreach_mode`. The API must send outreach in the plan's mode.

18. **`always_staffed` excludes breaks** (*v1.4, David*): an employee on a meal or rest break is not
    covering any role, including an `always_staffed` one; another employee must cover the break.
    (Retail practice: the leader on duty hands off LOD before a break.)

## Minimum wage (*v1.1*)

15. **`below_minimum_wage`** (hard): for every employee with at least one shift, if
    `wage_per_hour` < the law pack's `minimum_wage.dollars_per_hour` (the rule in effect on
    `Store.week_start`), the validator reports one violation per employee with that `law_rule_id`.
    The engine never changes wages: it schedules as normal, and the API's readiness report shows a
    failing "wages ≥ minimum wage" check naming the employees.
