"""Demo store: "Store #0417, Austin TX". Generated with a fixed seed, then hand-tuned for SPEC §7.

Regenerate fixtures + CSV exports:  uv run python -m shiftwright_scenarios.demo
"""
from __future__ import annotations

import math
import os
import random
from datetime import timedelta
from typing import Mapping

from shiftwright_contracts.models import (
    AvailabilityEntry,
    AvailabilityKind,
    CallOut,
    ConstraintKind,
    Jurisdiction,
    Source,
    StoreConfig,
)

from .callouts import DEFAULT_REPORTED_AT
from .fixtures import FIXTURES_DIR
from .generator import NORMAL_RATIO, compress_hourly, generate, required_hours
from .history import build_history
from .models import Scenario
from .narrative import build_narrative

DEMO_SEED = 417
SATURDAY = 5
# Placeholders in the committed fixture; apply_demo_phones() swaps in DEMO_PHONE_1/2 at runtime.
# Real demo numbers never go in the repo.
PLACEHOLDER_PHONES = ("+15125550198", "+15125550199")
CASHIER_HABIT = ("cashier", 17, 22, 2)  # leader always ran >=2 cashiers 17:00-22:00
EXTRA_CASHIERS = 6
# Nudges so a real engine schedule matches the demo script (checked by verify_demo):
# the call-outs like Saturday truck mornings; the demo phones have Saturdays off, so they are
# free to be called in. Weights are $/hour of overlap; $60/h + wage is above every gap penalty
# of the roles they're trained for (max $70/h), so the weekly solve never schedules them Saturday.
CALLOUT_PREFERRED_ON = (4 * 60, 14 * 60, 15.0)
PHONE_PREFERRED_OFF = 60.0
PHONE_TIME_OFF_DAYS = (0, 1, 2, 6)  # Mon, Tue, Wed, Sun of the demo week


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
    cfg.budget.weekly_hours_cap = round(need * NORMAL_RATIO * 2) / 2

    # Demo phones go to the two people with the best call-in record, trained for truck + register.
    phone_pool = [e for e in emps if e.age >= 18 and e.home_department_id not in ("leadership",)
                  and e.status.value == "part_time" and e.id not in taken and _no_unavailable(e)]
    demo_people = rng.sample(phone_pool, 2)
    for e in emps:  # nobody else matches their call-in record
        a = e.attendance
        if a.callins_offered_90d and a.callins_accepted_90d / a.callins_offered_90d >= 0.8:
            a.callins_accepted_90d = math.floor(a.callins_offered_90d * 0.7)
    for e, phone, (offered, accepted), wage in zip(demo_people, PLACEHOLDER_PHONES, [(10, 9), (9, 8)], [15.75, 16.25]):
        e.phone = phone
        e.attendance.callins_offered_90d, e.attendance.callins_accepted_90d = offered, accepted
        e.attendance.callouts_90d = 0
        e.wage_per_hour = wage
        for r in ("truck_unload", "cashier"):
            if r not in e.trained_role_ids:
                e.trained_role_ids.append(r)
        e.availability.append(AvailabilityEntry(weekday=SATURDAY, start=0, end=1440,
                                                kind=AvailabilityKind.preferred_off,
                                                weight_dollars=PHONE_PREFERRED_OFF,
                                                note="Saturdays off; happy to pick up a shift if asked."))
        # Time off this week (one-off dates, so history is unaffected): their weekly hours stay
        # well under max_hours_week and a Saturday call-in fits.
        for wd in PHONE_TIME_OFF_DAYS:
            e.availability.append(AvailabilityEntry(on_date=cfg.store.week_start + timedelta(days=wd), start=0,
                                                    end=1440, kind=AvailabilityKind.unavailable,
                                                    source=Source.leader, note="Approved time off."))
    taken += [e.id for e in demo_people]

    # Saturday 06:04: three call-outs on truck day (one unload, one PIT, one register).
    callouts: list[CallOut] = []
    for role in ("truck_unload", "pit_operator", "cashier"):
        cands = [e.id for e in emps if role in e.trained_role_ids and e.age >= 18 and e.id not in taken
                 and e.home_department_id != "leadership"]
        pick = rng.choice(cands)
        taken.append(pick)
        start, end, w = CALLOUT_PREFERRED_ON
        next(e for e in emps if e.id == pick).availability.append(
            AvailabilityEntry(weekday=SATURDAY, start=start, end=end, kind=AvailabilityKind.preferred_on,
                              weight_dollars=w, note="Likes the Saturday truck morning."))
        callouts.append(CallOut(employee_id=pick, day=SATURDAY, reported_at=DEFAULT_REPORTED_AT))

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
            "demo_phone_employee_ids": [e.id for e in demo_people],
            "callout_employee_ids": [c.employee_id for c in callouts],
            "history_pattern": "cashier headcount >= 2 for every hour 17:00-22:00, all 8 weeks",
        },
        notes=[
            "Built by shiftwright_scenarios.demo.build_demo_scenario (seed 417, M, normal) and hand-tuned.",
            "Call-outs carry a Saturday-morning preferred_on and the demo phones a Saturday preferred_off, so "
            "the engine schedules the former and leaves the latter free to call in. Check with "
            "`uv run python -m shiftwright_scenarios.verify_demo`.",
        ],
    )
    return Scenario(config=cfg, history=history, narrative=narrative, callout_events=callouts, expected=expected)


def apply_demo_phones(cfg: StoreConfig, env: Mapping[str, str] | None = None) -> StoreConfig:
    """Copy of cfg with the placeholder phones replaced by DEMO_PHONE_1/2 (when set)."""
    env = os.environ if env is None else env
    out = cfg.model_copy(deep=True)
    for placeholder, var in zip(PLACEHOLDER_PHONES, ("DEMO_PHONE_1", "DEMO_PHONE_2")):
        if env.get(var):
            for e in out.employees:
                if e.phone == placeholder:
                    e.phone = env[var]
    return out


def write_fixtures() -> None:
    from .exports import write_exports

    sc = build_demo_scenario()
    (FIXTURES_DIR / "demo_scenario.json").write_text(sc.model_dump_json(indent=2) + "\n")
    (FIXTURES_DIR / "demo_store.json").write_text(sc.config.model_dump_json(indent=2) + "\n")
    write_exports(sc, FIXTURES_DIR / "exports")


if __name__ == "__main__":
    write_fixtures()
    print(f"wrote demo fixtures and exports under {FIXTURES_DIR}")
