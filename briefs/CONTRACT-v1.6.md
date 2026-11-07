# Contract v1.6: store-specific rules (Tier 1)

*Drafted Sat Nov 7 ~03:00 CT by the coordinator at David's request. Contracts are owned by David:
implement, show the diff summary, then tag.*

## Goal

A leader can state a rule that isn't law and isn't one of the 11 built-in kinds — "always two
keyholders when we're open", "never more than three minors on at once", "someone who speaks Spanish
on every shift", "the Thursday 7 AM huddle is the whole front end" — and have the engine enforce it
**exactly**, the validator check it **independently**, and the receipt list it next to the law.

Today those go to `StoreConfig.unmodeled`, which the engine ignores. That is the gap between
"retail scheduler" and "any hourly business": every business has rules of its own, and the leader is
the only source of them.

**Not code.** The agent never writes code or expressions into a customer's engine. It fills in a
small structured rule, the engine compiles it to linear constraints, and the validator recomputes it
from the finished schedule. Anything the structure can't express still goes to `unmodeled`, with a
reason the agent must say out loud.

## Rules for this change

- One batch, one version: `CONTRACT_VERSION = "1.6.0"`, tag `contracts-v1.6`. Agents rebase once.
- **Additive only.** No renames, no removals. Every new field has a default; existing fixtures and
  all five demos must be byte-compatible after regeneration (only the version stamp changes).
- No new dependency. No generated code, no eval of strings.
- Tag only after WS1's split shifts are on `main` (one rebase for everyone).

## Fields

```python
class Employee(BaseModel):
    ...
    tags: list[str] = []
    # v1.6. Leader-defined labels, e.g. ["keyholder", "spanish", "cpr", "trainee"].
    # Normalized: lower-case, [a-z0-9_]+ (the importer/agent must normalize; the validator reports
    # anything else as `malformed`). Tags are not law and carry no pay or eligibility meaning.

class ConstraintKind(str, Enum):
    ...
    custom_count = "custom_count"   # v1.6
```

`Constraint.params` for `custom_count`:

```python
# WHO — all present conditions must hold (AND). Empty match matches everyone.
match = {
  "employee_tags": [str],      # employee has every listed tag
  "role_ids": [str],           # every RoleSegment of the counted shift is one of these
  "employee_ids": [str],
  "age_below": int | None,     # age at Store.week_start
  "age_at_least": int | None,
  "employment": "full" | "part" | None,
}

# WHAT is counted
measure = "on_duty_at_once"    # employees working in the same slot
        | "present_in_window"  # each matched employee has a shift covering the whole window
        | "hours"              # paid hours (#20 paid breaks included)
        | "shifts"             # number of shifts
        | "days_worked"        # distinct days with >= 1 shift

# PER what
per = "slot"                   # each Store.slot_minutes step of the window (on_duty_at_once only)
    | "day"                    # each day (present_in_window only)
    | "employee_day"           # each (employee, day) — hours/shifts/shifts per person per day
    | "employee_week"          # each employee over the week
    | "store_day"              # whole store, per day
    | "store_week"             # whole store, over the week

# WHEN
window = "store_hours" | "staff_hours" | {"days": [int] | "all", "start": int, "end": int}
# start/end are minutes from midnight, e.g. 420..480 for 07:00-08:00; end may exceed 1440 for
# overnight. "store_hours" uses Store.hours + pre/post open minutes; "staff_hours" is the union of
# candidates (drafting/onboarding helper only).

# THE LIMIT
comparator = "at_least" | "at_most" | "exactly"
value = float
```

`Constraint.strength` decides hard vs soft; a soft rule uses `weight_dollars` **per unit** of
shortfall (per hour for `hours`/`on_duty_at_once`/`present_in_window`, per shift for `shifts`, per
day for `days_worked`). `Constraint.note` must be the plain-English restatement the leader approved.

## Semantics (new #25 in SEMANTICS.md)

25. **Custom rules.** `custom_count` is evaluated on the schedule, by the same code in engine and
    validator (shared helper in `contracts`-adjacent package, not copies):
    - A slot counts an employee as on duty iff a segment of one of their shifts overlaps the slot and
      it is not a break (#18). `on_duty_at_once` is measured per `Store.slot_minutes` step inside the
      window; slots with zero demand still count.
    - `hours` is paid hours; `days_worked` counts a day once; `shifts` counts shifts whose start is in
      the window (for `day`/`employee_day` scopes) or whose start day is one of the window's days.
    - `present_in_window` requires one shift of the employee to cover the entire window (a break
      inside it does not break coverage unless the break is longer than 15 minutes).
    - Scope: `employee_day`/`employee_week` iterate each matched employee; `store_day`/`store_week`
      aggregate every matched employee.
    - Hard rules are hard constraints in CP-SAT. Soft rules add `weight_dollars × unit shortfall` to
      the objective and are reported as soft violations like any other soft rule.
    - **Unsat explanations:** when a custom rule is the reason a solve is infeasible, the engine's
      conflict text names it as `constraint:<id> ("<note>")`, like a law rule id.
    - **Validator:** a new `ViolationCode.custom_rule` reports the rule id, the scope (day/slot/employee)
      and the observed vs required count. `validate_fix` treats custom rules exactly like other soft
      and hard rules, including on the plan's schedules.
    - An `unmodeled` note is still required for anything outside this shape; the agent may not
      "approximate" a rule with a different measure without saying so on the confirm card.

## Work by workstream

- **WS1 (engine):** compile every `measure`/`per`/`window` combination above to CP-SAT; soft weights;
  infeasibility naming; `fix_day` respects custom rules; metrics unchanged. Perf: no measurable cost
  on the demo stores (one pass over candidate shifts to precompute tag/role membership).
- **WS2 (validator):** the shared evaluator, `custom_rule` code + goldens (at-least keyholders missed,
  at-most minors exceeded, trainee over hours, huddle window missed, unknown employee tag ⇒
  `malformed`), agreement test against the engine on the 5 demo stores with 3 custom rules each.
- **WS6 (agent):** `add_constraint` accepts `custom_count`; new prompt section mapping leader speech
  to the shape, with the worked examples in this brief; **confirm card** restating it in one sentence
  ("At least 2 people tagged keyholder, whenever you're open. Hard rule?") and showing the exact
  match/measure/window; refuse to save until the leader confirms; if the rule doesn't fit, save
  `unmodeled` with the reason. Employee tags are collected on a small card (add/rename/remove tags,
  assign to people) and are leader-owned decisions (WS6's owner-only rule).
- **WS7 (UI):** tags as chips on the People table and employee view; a custom-rule row in the
  rulebook and the compliance receipt (source = leader, hard/soft, the note, and the citation slot
  empty); a violation line in the receipt for custom rules; infeasibility text renders rule ids with
  the leader's note instead of the raw id.
- **WS4 (scenarios):** the Harbor Grill demo gets two custom rules that matter to the story — "at
  least 2 keyholders whenever open" and "at most 2 minors on at once" — and the Chicago taqueria
  template gets "at least 1 Spanish speaker per shift" as a soft rule. Fixtures regenerate with the
  rules; engine at 30 s still feasible, 0 hard.
- **WS5 (evals):** one realistic-suite scenario narrative that states a custom rule; score it under
  the true config + law (`expected` unchanged) and note in the method box that custom rules are part
  of the ground-truth store, not of the baseline's prompt for the solver suite.

## Acceptance

- `uv run pytest -q -m "not slow"` green; web build + tests green.
- All five demo stores: feasible, validator 0 hard, coverage not worse than before by >0.5 pp.
- Chat cold start "I need two keyholders on at all times and never more than two minors" produces one
  `custom_count` constraint, shown on a confirm card in that plain English, saved only after the
  leader confirms, and the resulting receipt lists it.
- A store where the keyholder rule cannot be met returns infeasible naming that constraint, and the
  message quotes the leader's note.
- Anything not expressible lands in `unmodeled` with a reason (no silent approximation).

## Out of scope (say so in the demo if asked)

Soft "preferences" beyond a dollar weight (e.g. "Ana prefers mornings" is `preferred_role`/availability
today); rules depending on another person's *identity* other than `not_together`; recurring
multi-week patterns; per-rule effective dates; any rule that needs data the store doesn't have.
