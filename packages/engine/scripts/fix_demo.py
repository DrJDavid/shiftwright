"""Demo call-out: solve the demo week, then fix Saturday 06:04 for the scenario's call-outs.

    uv run python packages/engine/scripts/fix_demo.py [solve_time_limit_s] [austin|chicago|seattle|sf]
"""
from __future__ import annotations

import sys
import time

from shiftwright_contracts.models import CallOut, FixRequest
from shiftwright_engine import solve_week
from shiftwright_engine.fix import fix_day
from shiftwright_scenarios.callouts import DEFAULT_REPORTED_AT
from shiftwright_scenarios.demo import SATURDAY
from shiftwright_scenarios.fixtures import load_demo_scenario
from shiftwright_scenarios.verify_demo import with_law_pack
from shiftwright_validator import validate

loc = sys.argv[2] if len(sys.argv) > 2 else "austin"
sc = load_demo_scenario(loc)
cfg = with_law_pack(sc.config)
ids = sc.expected["demo"]["callout_employee_ids"]
t = time.perf_counter()
week = solve_week(cfg, time_limit_s=float(sys.argv[1]) if len(sys.argv) > 1 else 30)
print(f"solve_week {week.status} {time.perf_counter() - t:.1f}s cov={week.metrics.coverage_pct}")
for eid in ids:
    print("  call-out", eid, [(s.start, s.end, sorted({g.role_id for g in s.segments}))
                              for s in week.shifts if s.employee_id == eid and s.day == SATURDAY])
from shiftwright_engine.premium import MODES  # noqa: E402
req = FixRequest(config=cfg, schedule=week, day=SATURDAY, now=DEFAULT_REPORTED_AT,
                 callouts=[CallOut(employee_id=e, day=SATURDAY, reported_at=DEFAULT_REPORTED_AT) for e in ids])
t = time.perf_counter()
plan = fix_day(req)
print(f"fix_day {time.perf_counter() - t:.1f}s mode={plan.outreach_mode} cov before={plan.coverage_before_pct} "
      f"best={plan.coverage_after_best_pct} worst={plan.coverage_after_worst_pct}")
for a in plan.actions:
    print("  action", a.lever.value, a.employee_id, a.role_id, a.start, a.end, a.added_cost_dollars, "|", a.rationale)
for c in plan.outreach_queue:
    print("  queue", c.rank, c.employee_id, c.proposed_shift.start, c.proposed_shift.end, c.added_cost_dollars,
          c.est_accept_prob, "|", c.why)
print("  demo phones:", sc.expected["demo"].get("demo_phone_employee_ids"))
for name in ("schedule_if_all_accept", "schedule_if_none_accept"):
    s = getattr(plan, name)
    hard = [v for v in validate(cfg, s).violations if (v.severity == "hard" or v.code.value == "metrics_mismatch")
            and v.code.value != "below_minimum_wage"]
    print(name, s.status, "hard:", [(v.code.value, v.message[:120]) for v in hard])
# nothing before now changed
before = {(s.employee_id, s.day): s for s in week.shifts}
for name in ("schedule_if_all_accept", "schedule_if_none_accept"):
    for s in getattr(plan, name).shifts:
        o = before.get((s.employee_id, s.day))
        if s.day != SATURDAY and o is not None and o.model_dump(exclude={"why"}) != s.model_dump(exclude={"why"}):
            print("CHANGED other day", name, s.employee_id, s.day)
