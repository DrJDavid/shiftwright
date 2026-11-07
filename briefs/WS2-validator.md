# WS2 — Validator (independent referee)

**Folder:** `packages/validator/` (`shiftwright_validator`) · **Oversight:** David
**Read first:** `SPEC.md`, `contracts/models.py`

## Goal
Given a `StoreConfig` (with `law_pack`) and **any** `Schedule` (ours, Grok's, a raw chat model's,
hand-written), list every rule broken and recompute the true metrics. This is the referee for the
whole eval, so it must be simple, readable, and independent.

## Hard requirements
- **Do not import `shiftwright_engine`.** Do not read engine code. Implement from the contracts and
  this brief only. (If both share a misunderstanding, the evals become meaningless.)
- Plain Python loops over slots. Clarity over speed. Under 1 s for the demo store is plenty.
- Tolerate garbage. Baseline LLM schedules will have unknown ids, overlapping segments, times off
  the grid, end < start, missing fields. Report each as a violation (`malformed`, `unknown_entity`);
  never crash. Provide `parse_schedule_lenient(raw: dict|str) -> tuple[Schedule|None, list[Violation]]`.

## Public interface
```python
validate(config: StoreConfig, schedule: Schedule) -> ValidationReport
parse_schedule_lenient(raw) -> tuple[Schedule | None, list[Violation]]
recompute_metrics(config, schedule) -> ScheduleMetrics
```

## Checks (one function each, one `ViolationCode` each)
Malformed and unknown entities · segments tile the shift minus breaks · not_trained ·
unavailable · double_booked · outside_store_window (pre-open/post-close allowance) ·
max_hours_week · shift_length · rest_between_shifts · days_per_week · consecutive_days ·
budget_hours (cap + approvals) · budget_dollars · overtime_not_allowed · meal_break and
rest_break (per the law pack) · minor_hours · minor_prohibited_role (via `role_tags` and
`Role.min_age`) · always_staffed · metrics_mismatch (claimed vs recomputed, >1% or >$1) ·
soft costs (severity `soft`).

Only `confirmed` constraints count. Coverage gaps are not violations; they show up in
`recomputed_metrics.coverage_pct` and `gap_penalty_dollars`.

## Acceptance tests
- One hand-built "golden bad schedule" per ViolationCode, each triggering exactly that code.
- A hand-built perfect schedule for tiny_store → `passed=True`, metrics match hand calculation.
- Fuzz: 200 random mutations of a valid schedule never raise an exception.
- Once WS1 lands: every engine schedule on the S scenarios passes. (If not, file the disagreement in STATUS.md; David decides who is wrong.)
