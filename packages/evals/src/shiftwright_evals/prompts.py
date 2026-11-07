"""Baseline prompts. The same inputs Shiftwright gets, explained as well as we can explain them.

A weak prompt would make the comparison meaningless, so the prompt spells out the time
conventions, every hard rule the validator checks (in plain English, pointing at the config
fields, never at law from memory: the law itself is the `law_pack` inside the config), the
objective, the output schema, and how to say "infeasible".
"""
from __future__ import annotations

import json

from shiftwright_contracts.models import CallOut, Schedule, StoreConfig

INSTRUCTION = (
    "Produce the lowest-cost schedule that breaks no hard rule. If no such schedule exists, "
    "set status 'infeasible' and explain."
)

SYSTEM = (
    "You are an expert retail workforce scheduler and a careful constraint solver. You are given "
    "a complete store configuration as JSON. You return exactly one JSON object and nothing else "
    "that could be mistaken for it. Correctness against the hard rules matters more than anything; "
    "an automated referee checks every shift."
)

TIME_CONVENTIONS = """\
TIME CONVENTIONS (read carefully)
- The schedule covers exactly one week starting on store.week_start (a Monday).
- `day` is an integer 0..6 relative to week_start (0 = Monday, 6 = Sunday).
- Times are integers: minutes after local midnight of that day (e.g. 08:00 = 480, 17:30 = 1050).
  Overnight shifts may end after 1440 (22:00-06:30 next day = 1320..1830). A shift belongs to the day it starts.
- Intervals are half-open [start, end).
- Shift start/end, demand and availability times are multiples of store.slot_minutes.
  Break start/end, and role-segment boundaries that touch a break, only need to be multiples of 5.
- Money is USD; hours are decimal hours."""

HARD_RULES = """\
HARD RULES (any break of these makes the schedule wrong)
1. Use only employee ids, role ids and the store id that exist in the config. Never invent people.
2. Training: an employee may only work a role listed in their trained_role_ids.
3. Age: never put an employee in a role whose Role.min_age exceeds their age, or in a role whose
   role_tags match a law_pack `minor_prohibited_roles` rule for their age.
4. Availability: never schedule inside an employee's `unavailable` window (weekday = recurring,
   on_date = one-off; compare against week_start + day).
5. No employee works two overlapping shifts.
6. Shifts must lie within [open - store.pre_open_minutes, close + store.post_close_minutes] of that day.
7. Paid hours = shift span minus unpaid breaks (paid breaks count). Each employee's weekly paid hours
   must not exceed Employee.max_hours_week.
8. Budget: total paid hours <= budget.weekly_hours_cap + sum(approvals.extra_hours). If
   budget.weekly_dollar_cap is set, total wage cost + law premiums <= cap + sum(approvals.extra_dollars).
9. Overtime: only the law_pack's weekly_overtime / daily_overtime rules create overtime (paid at their
   multiplier, inside wage cost). If budget.overtime_allowed is false, nobody may exceed those thresholds.
10. Every `constraints` entry with strength "hard" and status "confirmed" must hold (provisional and
    rejected ones are ignored). Kinds: min/max_shift_length {minutes} (clock span, breaks included),
    min_rest_between_shifts {minutes}, max_days_per_week {days}, max_consecutive_days {days},
    always_staffed {role_id, windows: "store_hours"|"staff_hours"} (at least one person in that role
    at every minute of the window), and the soft-family kinds when marked hard.
11. Law pack (config.law_pack.rules; this is the only source of law, do not use outside knowledge):
    - meal_break {after_minutes, duration, paid, latest_start_minute_of_shift, waivable_under_minutes}:
      a shift whose span exceeds after_minutes needs a meal break of at least `duration` minutes,
      starting no later than latest_start_minute_of_shift minutes into the shift; shifts no longer than
      waivable_under_minutes are exempt. Multiple meal rules stack (2nd meal for longer shifts).
    - rest_break {per_minutes_worked, duration, paid}: floor(span / per_minutes_worked) rest breaks
      of at least `duration` minutes (if not_required_under_minutes is present, shifts at or above it
      need at least one).
    - minor_limits {age_min, age_max, school_week, max_hours_day, max_hours_week, earliest_start,
      latest_end, ...}: limits for employees in that age range. If store.school_week is null, apply
      every minor_limits rule (Mon-Fri are school days); true = only school_week rules; false = only
      non-school-week rules.
    - min_rest_between_shifts {minutes, premium_multiplier}: with a multiplier it is a pay premium,
      without one it is a hard minimum rest.
    - minimum_wage: never schedule an employee whose wage_per_hour is below it.
12. Shift structure: `segments` must tile [start, end) minus the breaks exactly, with no gaps or
    overlaps; a shift may change role mid-shift by using several segments. Breaks lie inside the shift."""

OBJECTIVE = """\
OBJECTIVE (minimise, subject to the hard rules)
  total wage cost (incl. overtime premium) + law premiums
  + coverage gap penalty: for every minute a demand requirement is under-staffed, missing headcount
    x Role.gap_penalty_per_hour / 60
  + soft penalties: each soft confirmed constraint costs weight_dollars per unit (per hour short or
    overlapping, per extra occurrence or day), preferred_off availability costs weight_dollars per hour.
Coverage is soft: leaving a demand slot uncovered is allowed and priced. Never break a hard rule to fill
a gap. Demand for the same role and day does not overlap; headcount is per minute."""

OUTPUT_WEEKLY = """\
OUTPUT
Return a single JSON object conforming to the Schedule JSON Schema below, inside one ```json fenced
block, with no other JSON in your reply. Use compact JSON (no indentation) so it fits.
- store_id, week_start and config_version must copy the config's store.id, store.week_start and config_version.
- produced_by: "baseline".
- status: "feasible" (or "optimal" if you are sure no cheaper legal schedule exists) when every hard
  rule holds; "infeasible" when no schedule can satisfy all hard rules.
- If infeasible: fill `infeasibility` with the ids of the conflicting constraints
  (conflicting_constraint_ids), law rules (conflicting_law_rule_ids), and other items such as
  "budget.weekly_hours_cap" or "employee:<id>.max_hours_week" (conflicting_other), plus a plain
  summary. You may still return your best shifts.
- `gaps`, `soft_violations` and `metrics` are optional. If you include `metrics`, they are checked
  against a recomputation and wrong numbers count as an error; omit them if unsure.
Example shift: {"id":"s1","employee_id":"e001","day":0,"start":480,"end":990,
"breaks":[{"start":720,"end":750,"kind":"meal","paid":false}],
"segments":[{"role_id":"cashier","start":480,"end":720},{"role_id":"cashier","start":750,"end":990}]}"""

RETRY = (
    "Your previous reply could not be parsed as the requested JSON object ({error}). Reply again with "
    "only the complete JSON object in a single ```json fenced block."
)


def schema_json() -> str:
    return json.dumps(Schedule.model_json_schema(), separators=(",", ":"))


def config_json(config: StoreConfig) -> str:
    return config.model_dump_json()


def weekly_messages(config: StoreConfig) -> list[dict]:
    user = "\n\n".join([
        f"TASK\n{INSTRUCTION}",
        TIME_CONVENTIONS,
        HARD_RULES,
        OBJECTIVE,
        OUTPUT_WEEKLY,
        f"SCHEDULE JSON SCHEMA\n<schedule_schema>\n{schema_json()}\n</schedule_schema>",
        f"STORE CONFIG (complete, including the law pack)\n<store_config>\n{config_json(config)}\n</store_config>",
        "Work through demand day by day and role by role, check each shift against every hard rule "
        "before including it, then output the JSON.",
    ])
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


REPAIR_TASK = """\
TASK
It is day {day} ({dayname}) at minute {now} ({hhmm}). The employees below just called out for the rest of
that day. Repair the schedule: produce the lowest-cost revised schedule that breaks no hard rule, plus an
ordered call list of off-duty employees to phone. If no legal repair restores coverage, say what stays
uncovered. Levers you may use: call in off-duty staff, extend or move shifts (only after `now`), reassign
roles for the rest of the day, and leave low-priority coverage uncovered.
Repair rules (hard, on top of the schedule hard rules):
- Nothing before minute {now} on day {day} may change, and nothing on earlier days may change.
- Called-out employees must not work on day {day} at or after the minute they reported.
- The revised schedule assumes everyone on your call list says yes."""

OUTPUT_REPAIR = """\
OUTPUT
Return one JSON object inside a single ```json fenced block:
{"schedule": <the complete revised week as a Schedule object, all days, same rules as the input>,
 "call_list": [{"rank":1,"employee_id":"...","role_id":"...","start":<minute>,"end":<minute>,"why":"..."}]}
Use compact JSON. produced_by: "baseline". Omit metrics unless you are sure they are exact."""

DAYNAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def repair_messages(config: StoreConfig, schedule: Schedule, callouts: list[CallOut], day: int, now: int) -> list[dict]:
    task = REPAIR_TASK.format(day=day, dayname=DAYNAMES[day], now=now, hhmm=f"{now // 60:02d}:{now % 60:02d}")
    callouts_json = json.dumps([c.model_dump(mode="json") for c in callouts])
    user = "\n\n".join([
        task,
        TIME_CONVENTIONS,
        HARD_RULES,
        OBJECTIVE,
        OUTPUT_REPAIR,
        f"SCHEDULE JSON SCHEMA\n<schedule_schema>\n{schema_json()}\n</schedule_schema>",
        f"STORE CONFIG (complete, including the law pack)\n<store_config>\n{config_json(config)}\n</store_config>",
        f"CURRENT SCHEDULE\n<current_schedule>\n{schedule.model_dump_json()}\n</current_schedule>",
        f"CALL-OUTS\n<callouts>\n{callouts_json}\n</callouts>",
    ])
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def render(messages: list[dict]) -> str:
    """prompt.txt: the exact messages sent, in order."""
    return "\n\n".join(f"### {m['role']}\n{m['content']}" for m in messages) + "\n"
