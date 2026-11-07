"""Demo stores. "Store #0417, Austin TX" plus the same store in other localities, each with a
different compliance story. Generated with a fixed seed, then hand-tuned for SPEC §7.

Every locality shares the staff, ids, demand, history and Saturday 06:04 call-outs. What changes:
jurisdiction, name/id, timezone, phone area codes, wages (raised to the resolved law-pack minimum
wage), and a few narrative sentences built from the resolved law pack (never hardcoded law).

Regenerate fixtures + CSV exports:  uv run python -m shiftwright_scenarios.demo
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import timedelta

from shiftwright_contracts.models import (
    AvailabilityEntry,
    AvailabilityKind,
    CallOut,
    ConstraintKind,
    AttendanceStats,
    Employee,
    EmploymentStatus,
    Jurisdiction,
    LawPack,
    LawRuleType,
)
from shiftwright_laws import resolve

from .callouts import DEFAULT_REPORTED_AT
from .fixtures import FIXTURES_DIR
from .catalog import FIRST_NAMES, LAST_NAMES, ROLES
from .generator import TIMEZONES, NORMAL_RATIO, _money, _lift_wages, compress_hourly, generate, minimum_wage, required_hours
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
# Synthetic: a national big-box chain's total headcount (order of magnitude of real ones). It only
# matters for law applicability thresholds (predictive_scheduling.applies_if_employees_over).
EMPLOYER_EMPLOYEE_COUNT = 400_000
POSTED_DAYS_BEFORE = 14  # schedule_posted_on = week_start - 14 days


@dataclass(frozen=True)
class Locality:
    key: str
    store_number: str
    city_label: str
    state: str
    city: str          # as the law resolver expects it
    area_code: str     # for the fake 555 phone numbers


LOCALITIES: dict[str, Locality] = {
    "austin": Locality("austin", "0417", "Austin", "TX", "austin", "512"),
    "chicago": Locality("chicago", "1123", "Chicago", "IL", "chicago", "312"),
    "seattle": Locality("seattle", "2231", "Seattle", "WA", "seattle", "206"),
    "sf": Locality("sf", "3305", "San Francisco", "CA", "san francisco", "415"),
}
DEFAULT_LOCALITY = "austin"


def _locality(key: str) -> Locality:
    if key not in LOCALITIES:
        raise ValueError(f"locality must be one of {sorted(LOCALITIES)}, got {key!r}")
    return LOCALITIES[key]


def _clock(minute: int) -> str:
    h, m = divmod(minute, 60)
    return f"{h % 12 or 12}{':%02d' % m if m else ''}{'am' if h < 12 else 'pm'}"


def _hours_word(minutes: int) -> str:
    return f"{minutes / 60:g} hours"


# Departments where the break-law variants ran short (low-penalty floor roles), and how many
# extra part-timers per point of break allowance above 1.0.
HIRE_DEPTS = ("general_merchandise", "grocery", "fulfillment", "front_of_store")
HIRES_PER_ALLOWANCE = 60  # 60 staff x (allowance - 1): Seattle/SF +6, Chicago +3
DAILY_OT_HIRES = 4        # a daily-OT threshold (CA: 8 h) means shorter shifts, so more heads


def _add_new_hires(rng: random.Random, cfg, loc: Locality, pack: LawPack, allowance: float,
                   lift: float) -> list[str]:
    n = round(HIRES_PER_ALLOWANCE * (allowance - 1))
    if any(r.type == LawRuleType.daily_overtime for r in pack.rules) and not cfg.budget.overtime_allowed:
        n += DAILY_OT_HIRES
    if n <= 0:
        return []
    used = {e.name for e in cfg.employees}
    names = [f"{f} {l}" for f in FIRST_NAMES for l in LAST_NAMES if f"{f} {l}" not in used]
    role_ids = {r.id for r in cfg.roles}
    ids: list[str] = []
    start = len(cfg.employees)
    for k, name in enumerate(rng.sample(names, n)):
        i = start + k
        dept = HIRE_DEPTS[k % len(HIRE_DEPTS)]
        dept_roles = [r for r in role_ids if ROLES[r][0] == dept and ROLES[r][2] <= 18]
        dept_roles.sort()
        trained = rng.sample(dept_roles, min(len(dept_roles), rng.choice([2, 2, 3])))
        if "cashier" not in trained and rng.random() < 0.5:
            trained.append("cashier")
        offered = rng.randint(0, 4)
        e = Employee(
            id=f"e{i + 1:03d}",
            name=name,
            phone=f"+1{loc.area_code}5550{100 + i % 100}",
            age=rng.randint(19, 40),
            home_department_id=dept,
            trained_role_ids=trained,
            status=EmploymentStatus.part_time,
            wage_per_hour=round(_money(rng.uniform(15, 18)) + lift, 2),
            min_hours_week=12.0,
            max_hours_week=29.0,
            availability=[],
            hire_date=cfg.store.week_start - timedelta(days=rng.randint(21, 49)),
            attendance=AttendanceStats(shifts_90d=rng.randint(10, 20), callouts_90d=rng.choice([0, 0, 1]),
                                       callins_offered_90d=offered, callins_accepted_90d=rng.randint(0, offered)),
        )
        cfg.employees.append(e)
        ids.append(e.id)
    return ids


def break_allowance(pack: LawPack, shift_minutes: int = 480) -> float:
    """Multiplier on the weekly hours cap so corporate's labor model funds legally required breaks.

    Paid rest breaks use paid hours without covering the floor (duration / per_minutes_worked).
    Unpaid meals on a typical 8-hour shift leave a hole someone else has to cover (duration / shift).
    1.0 when the pack has no break rules (Austin). Numbers come only from the pack's rule params.
    """
    extra = 0.0
    for r in pack.rules:
        if r.type == LawRuleType.rest_break and r.params.get("paid", True):
            extra += r.params["duration"] / r.params["per_minutes_worked"]
    meals = [r for r in pack.rules if r.type == LawRuleType.meal_break and r.params["after_minutes"] < shift_minutes]
    if meals:
        m = min(meals, key=lambda r: r.params["after_minutes"])
        extra += m.params["duration"] / shift_minutes
    return round(1 + extra, 4)


def locality_sentences(pack: LawPack, city_label: str) -> list[tuple[dict, str]]:
    """Leader-voice sentences about local rules, built only from the resolved law pack's rules.

    Each comes with a note dict {kind: "law_context", law_rule_id, ...} so evals can tell the intake
    agent heard context it should look up, not a store constraint to write down.
    """
    out: list[tuple[dict, str]] = []
    by_type: dict[LawRuleType, list] = {}
    for r in pack.rules:
        by_type.setdefault(r.type, []).append(r)

    def note(r, **kw) -> dict:
        return {"kind": "law_context", "law_rule_id": r.id, "type": r.type.value, **kw}

    for r in by_type.get(LawRuleType.predictive_scheduling, []):
        if r.level != "city":
            continue
        days = r.params.get("notice_days")
        if days:
            out.append((note(r, notice_days=days),
                        f"We're in {city_label}, so the schedule has to go up {days} days ahead, and changing it "
                        "after it's posted costs us premium pay. Corporate posts it on time."))
    for r in by_type.get(LawRuleType.min_rest_between_shifts, []):
        mult = r.params.get("premium_multiplier")
        if r.level == "city" and mult:
            out.append((note(r, minutes=r.params["minutes"], premium_multiplier=mult),
                        f"A clopen with less than {_hours_word(r.params['minutes'])} between shifts gets paid at "
                        f"{mult:g}x for those hours here, so I'd rather not."))
    meals = sorted(by_type.get(LawRuleType.meal_break, []), key=lambda r: r.params["after_minutes"])
    rests = by_type.get(LawRuleType.rest_break, [])
    if meals and not rests:
        m = meals[0]
        out.append((note(m, after_minutes=m.params["after_minutes"], duration=m.params["duration"]),
                    f"Anyone on past {_hours_word(m.params['after_minutes'])} gets a {m.params['duration']}-minute "
                    "meal break, leaders too."))
    if meals and rests:
        m, rr = meals[0], rests[0]
        out.append((note(m, after_minutes=m.params["after_minutes"], duration=m.params["duration"]),
                    f"Breaks matter here: a {m.params['duration']}-minute meal once a shift goes past "
                    f"{_hours_word(m.params['after_minutes'])}, and a {rr.params['duration']}-minute paid rest "
                    f"every {_hours_word(rr.params['per_minutes_worked'])}. Leaders included, so the LODs have "
                    "to cover each other's breaks."))
    for r in by_type.get(LawRuleType.daily_overtime, []):
        out.append((note(r, threshold_hours=r.params["threshold_hours"]),
                    f"Overtime here counts by the day too, anything past {r.params['threshold_hours']:g} hours "
                    "in a shift."))
    for r in by_type.get(LawRuleType.minimum_wage, []):
        if r.level == "city":
            out.append((note(r, dollars_per_hour=r.params["dollars_per_hour"]),
                        f"{city_label} minimum wage is ${r.params['dollars_per_hour']:.2f}; nobody here makes "
                        "less than that."))
    return out


def _no_unavailable(e) -> bool:
    return not any(a.kind == AvailabilityKind.unavailable for a in e.availability)


def build_demo_scenario(locality: str = DEFAULT_LOCALITY) -> Scenario:
    loc = _locality(locality)
    # Always generated as Austin, so every locality has the same staff, ids, demand and history.
    base = generate(DEMO_SEED, "M", "normal", Jurisdiction(state="TX", city="austin"))
    cfg = base.config.model_copy(deep=True)
    rng = random.Random("demo-0417")
    cfg.store.id = f"store-{loc.store_number}"
    cfg.store.name = f"Store #{loc.store_number}, {loc.city_label} {loc.state}"
    jur = Jurisdiction(state=loc.state, city=loc.city)
    cfg.store.jurisdiction = jur
    cfg.store.timezone = TIMEZONES.get(loc.state, "America/Chicago")
    cfg.store.school_week = True
    cfg.store.employer_employee_count = EMPLOYER_EMPLOYEE_COUNT
    cfg.store.schedule_posted_on = cfg.store.week_start - timedelta(days=POSTED_DAYS_BEFORE)
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
    pack = resolve(jur, on=cfg.store.week_start)
    allowance = break_allowance(pack)
    cfg.budget.weekly_hours_cap = float(math.floor(need * NORMAL_RATIO * allowance))

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

    # Locality: wages to the resolved minimum, local phone area code, law-pack narrative sentences.
    austin_wage_total = sum(e.wage_per_hour for e in emps)
    wage_law = minimum_wage(jur)
    lift = _lift_wages(emps, wage_law[0] if wage_law else None)
    for e in emps:
        e.phone = "+1" + loc.area_code + e.phone[5:]
    # Gap penalties are the store's value of an uncovered hour, in local dollars: scale them with the
    # local wage level so "cheaper to leave the gap" means the same thing as in Austin.
    gap_scale = round(sum(e.wage_per_hour for e in emps) / austin_wage_total, 4)
    if gap_scale != 1.0:
        for r in cfg.roles:
            r.gap_penalty_per_hour = float(round(r.gap_penalty_per_hour * gap_scale / 5) * 5)
    # Break laws take people off the floor, so these stores carry more heads. New hires (after the
    # history weeks), so ids e001-e060 and the history are identical in every locality.
    new_hires = _add_new_hires(random.Random(f"demo-0417|{loc.key}|hires"), cfg, loc, pack, allowance, lift)
    law_notes: list[dict] = []
    if loc.key != DEFAULT_LOCALITY:  # Austin's narrative stays as it was (TX: no city rules)
        extra = locality_sentences(pack, loc.city_label)
        law_notes = [n for n, _ in extra]
        if extra:
            narrative = narrative + "\n\n" + " ".join(t for _, t in extra)

    expected = dict(base.expected)
    expected.update(
        jurisdiction=jur.model_dump(),
        locality=loc.key,
        minimum_wage=wage_law[0] if wage_law else None,
        wage_lift=lift,
        law_context=law_notes,
        budget_break_allowance=allowance,
        gap_penalty_scale=gap_scale,
        new_hire_ids=new_hires,
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
            f"Built by shiftwright_scenarios.demo.build_demo_scenario({loc.key!r}) (seed 417, M, normal) and "
            "hand-tuned. Same staff and ids in every locality.",
            f"employer_employee_count={EMPLOYER_EMPLOYEE_COUNT} is synthetic (a national big-box chain).",
            "Check the call-outs against a real engine schedule with "
            "`uv run python -m shiftwright_scenarios.verify_demo`.",
        ],
    )
    return Scenario(config=cfg, history=history, narrative=narrative, callout_events=callouts, expected=expected)


def fixture_names(locality: str = DEFAULT_LOCALITY) -> tuple[str, str]:
    """(store file, scenario file). Austin keeps the original names."""
    _locality(locality)
    if locality == DEFAULT_LOCALITY:
        return "demo_store.json", "demo_scenario.json"
    return f"demo_store_{locality}.json", f"demo_scenario_{locality}.json"


def write_fixtures() -> None:
    from .exports import write_exports

    for key in LOCALITIES:
        sc = build_demo_scenario(key)
        store_f, scen_f = fixture_names(key)
        (FIXTURES_DIR / scen_f).write_text(sc.model_dump_json(indent=2) + "\n")
        (FIXTURES_DIR / store_f).write_text(sc.config.model_dump_json(indent=2) + "\n")
        if key == DEFAULT_LOCALITY:
            write_exports(sc, FIXTURES_DIR / "exports")
    from .food import build_demo_restaurant

    sc = build_demo_restaurant()
    (FIXTURES_DIR / "demo_scenario_restaurant.json").write_text(sc.model_dump_json(indent=2) + "\n")
    (FIXTURES_DIR / "demo_store_restaurant.json").write_text(sc.config.model_dump_json(indent=2) + "\n")


if __name__ == "__main__":
    write_fixtures()
    print(f"wrote demo fixtures and exports under {FIXTURES_DIR}")
