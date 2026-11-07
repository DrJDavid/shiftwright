"""Demo store: "Store #0417, Austin TX". Generated with a fixed seed, then hand-tuned for SPEC §7.

Regenerate fixtures + CSV exports:  uv run python -m shiftwright_scenarios.demo
"""
from __future__ import annotations

import math
import random

from shiftwright_contracts.models import (
    AvailabilityEntry,
    AvailabilityKind,
    CallOut,
    ConstraintKind,
    Jurisdiction,
)

from .callouts import DEFAULT_REPORTED_AT
from .fixtures import FIXTURES_DIR
from .generator import NORMAL_RATIO, compress_hourly, generate, required_hours
from .history import build_history
from .models import Scenario
from .narrative import build_narrative

DEMO_SEED = 417
SATURDAY = 5
CASHIER_HABIT = ("cashier", 17, 22, 2)  # leader always ran >=2 cashiers 17:00-22:00
EXTRA_CASHIERS = 6
DEMO_CALLOUTS = (("e034", "truck_unload"), ("e052", "pit_operator"), ("e053", "cashier"))
# Saturday 04:00-14:00 preferred_on ($/h of overlap) for the call-outs, so the weekly solve puts
# them on Saturday-morning shifts. None = no nudge.
CALLOUT_PREFERRED_ON: tuple[int, int, float] | None = (4 * 60, 14 * 60, 15.0)


def _no_unavailable(e) -> bool:
    return not any(a.kind == AvailabilityKind.unavailable for a in e.availability)


def build_demo_scenario() -> Scenario:
    base = generate(DEMO_SEED, "M", "normal", Jurisdiction(state="TX", city="austin"))
    cfg = base.config.model_copy(deep=True)
    rng = random.Random("demo-0417")
    cfg.store.id = "store-0417"
    cfg.store.name = "Store #0417, Austin TX"
    emps = cfg.employees
    taken: list[str] = []

    # Jordan and Casey: adult cashiers with open availability, so the rule actually bites.
    fos = [e for e in emps if e.home_department_id == "front_of_store" and "cashier" in e.trained_role_ids
           and e.age >= 18 and _no_unavailable(e)]
    jordan, casey = fos[0], fos[1]
    jordan.name = "Jordan " + jordan.name.split(" ", 1)[1]
    casey.name = "Casey " + casey.name.split(" ", 1)[1]
    taken += [jordan.id, casey.id]
    for c in cfg.constraints:
        if c.kind == ConstraintKind.not_together:
            c.params = {"employee_ids": [jordan.id, casey.id]}
            c.note = "Jordan and Casey shouldn't close together."

    # The law catch: a 17-year-old listed as forklift-trained.
    minor = next(e for e in emps if e.age < 18)
    minor.age = 17
    minor.trained_role_ids.append("pit_operator")
    taken.append(minor.id)

    # Corporate forecast asks for 1 cashier late on weekdays; history shows the leader always ran 2.
    prof: dict[tuple[str, int], list[tuple[int, bool]]] = {}
    for d in cfg.demand:
        row = prof.setdefault((d.role_id, d.day), [(0, False)] * 24)
        for h in range(d.start // 60, d.end // 60):
            row[h] = (d.headcount, d.source.value == "event")
    for day in range(4):
        row = prof[("cashier", day)]
        for h in range(19, 22):
            row[h] = (1, False)
    cfg.demand = compress_hourly(prof)
    # A deep register bench (realistic for a big-box front end) so the habit holds through Sunday.
    bench = [e for e in emps if "cashier" not in e.trained_role_ids and e.home_department_id != "leadership"
             and len(e.trained_role_ids) < 3]
    for e in rng.sample(bench, min(EXTRA_CASHIERS, len(bench))):
        e.trained_role_ids.append("cashier")
    need = required_hours(cfg.demand)
    # Whole hours, so the narrative's "Payroll is N hours" is exact.
    cfg.budget.weekly_hours_cap = float(math.floor(need * NORMAL_RATIO))

    # Saturday 06:04: three call-outs on truck day (one unload, one PIT, one register). Pinned ids
    # (the demo script names them); the asserts keep them honest if the generator changes.
    callouts: list[CallOut] = []
    by_id = {e.id: e for e in emps}
    for eid, role in DEMO_CALLOUTS:
        e = by_id[eid]
        assert role in e.trained_role_ids and e.age >= 18 and e.home_department_id != "leadership", eid
        assert eid not in taken, eid
        taken.append(eid)
        if CALLOUT_PREFERRED_ON is not None:
            start, end, w = CALLOUT_PREFERRED_ON
            e.availability.append(AvailabilityEntry(weekday=SATURDAY, start=start, end=end,
                                                    kind=AvailabilityKind.preferred_on, weight_dollars=w,
                                                    note="Likes the Saturday truck morning."))
        callouts.append(CallOut(employee_id=eid, day=SATURDAY, reported_at=DEFAULT_REPORTED_AT))

    trucks = base.expected["truck_days"]
    history = build_history(random.Random("demo-0417|history"), cfg, floors=[CASHIER_HABIT])
    narrative, facts, _, _ = build_narrative(random.Random("demo-0417|narrative"), cfg, trucks)

    expected = dict(base.expected)
    expected.update(
        required_hours=need,
        narrative_facts=facts,
        narrative_omissions=[],
        narrative_contradictions=[],
        callout_day=SATURDAY,
        traps={"minor_pit_trained": [minor.id]},
        demo={
            "jordan_id": jordan.id,
            "casey_id": casey.id,
            "minor_pit_id": minor.id,
            "callout_employee_ids": [c.employee_id for c in callouts],
            "history_pattern": "cashier headcount >= 2 for every hour 17:00-22:00, all 8 weeks",
        },
        notes=[
            "Built by shiftwright_scenarios.demo.build_demo_scenario (seed 417, M, normal) and hand-tuned.",
            "Check the call-outs against a real engine schedule with "
            "`uv run python -m shiftwright_scenarios.verify_demo`.",
        ],
    )
    return Scenario(config=cfg, history=history, narrative=narrative, callout_events=callouts, expected=expected)


def write_fixtures() -> None:
    from .exports import write_exports

    sc = build_demo_scenario()
    (FIXTURES_DIR / "demo_scenario.json").write_text(sc.model_dump_json(indent=2) + "\n")
    (FIXTURES_DIR / "demo_store.json").write_text(sc.config.model_dump_json(indent=2) + "\n")
    write_exports(sc, FIXTURES_DIR / "exports")


if __name__ == "__main__":
    write_fixtures()
    print(f"wrote demo fixtures and exports under {FIXTURES_DIR}")
