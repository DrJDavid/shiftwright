"""Food-service (restaurant) scenarios: generate(..., sector="food"). Deterministic per arguments.

A full-service restaurant and bar: lunch and dinner peaks, Fri/Sat heavier, a Thursday private
event, split shifts allowed (Store.max_shifts_per_day = 2). Servers and bartenders are tipped roles
(Role.tipped) with Employee.tipped_wage_per_hour set to the resolved law pack's
tipped_minimum_wage.cash_wage_per_hour, or the full minimum wage when the pack has no tipped rule
(SEMANTICS #15/#20). Role tags (ROLE_TAGS) are names only; which ones a law bans for minors comes
from data/laws.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from shiftwright_contracts.models import (
    AttendanceStats,
    AvailabilityEntry,
    AvailabilityKind,
    Budget,
    CallOut,
    Constraint,
    ConstraintKind,
    DayHours,
    Department,
    Employee,
    EmploymentStatus,
    Event,
    EventKind,
    Jurisdiction,
    LawPack,
    LawRuleType,
    Role,
    RuleStatus,
    Sector,
    Source,
    Store,
    StoreConfig,
    Strength,
)
from shiftwright_laws import resolve

from .catalog import DAY_NAMES, FIRST_NAMES, LAST_NAMES, TIMEZONES
from .history import build_history
from .models import Scenario

WEEK_START = date(2026, 11, 9)
DEPARTMENTS = [("front_of_house", "Front of House"), ("back_of_house", "Back of House"),
               ("management", "Management")]
# role_id: (department_id, name, gap_penalty_per_hour, tipped, description)
ROLES: dict[str, tuple[str, str, float, bool, str]] = {
    "manager_on_duty": ("management", "Manager on Duty", 100.0, False, "Runs the floor and the money while open."),
    "server": ("front_of_house", "Server", 60.0, True, "Takes orders and runs tables."),
    "bartender": ("front_of_house", "Bartender", 50.0, True, "Bar service and drinks for the floor."),
    "host": ("front_of_house", "Host", 30.0, False, "Greets guests, seats tables, manages the wait list."),
    "line_cook": ("back_of_house", "Line Cook", 80.0, False, "Works the hot line: grill, saute, fryer."),
    "prep_cook": ("back_of_house", "Prep Cook", 40.0, False, "Prep before service, including the meat slicer."),
    "dishwasher": ("back_of_house", "Dishwasher", 40.0, False, "Dish pit and kitchen cleanup."),
}
ROLE_TAGS = {"bartender": ["alcohol_service"], "line_cook": ["cooking", "fryer"], "prep_cook": ["meat_slicer"]}
# Store policy (not law): only 21+ staff are trained to tend bar; minors aren't trained on the line or slicer
# outside legal_trap / the demo, so any law catch is deliberate.
ADULT_ONLY_TRAINING = {"bartender": 21, "line_cook": 18, "prep_cook": 18, "manager_on_duty": 21}

HOURS = {0: (660, 1320), 1: (660, 1320), 2: (660, 1320), 3: (660, 1320), 4: (660, 1380), 5: (660, 1380),
         6: (660, 1260)}  # Mon-Thu 11-22, Fri-Sat 11-23, Sun 11-21
PRE_OPEN, POST_CLOSE = 120, 60
SIZE_STAFF = {"S": 18, "M": 32, "L": 60}
SIZE_MANAGERS = {"S": 3, "M": 4, "L": 6}
SIZE_SCALE = {"S": 0.6, "M": 1.0, "L": 1.8}
BUDGET_RATIO = {"easy": 1.2, "tight": 0.9}
NORMAL_RATIO = 1 / 1.05
EVENT_DAY, EVENT_START, EVENT_END = 3, 18 * 60, 22 * 60
EVENT_LABEL = "Rehearsal dinner (40 guests)"
EVENT_EXTRA = {"server": 2, "bartender": 1, "line_cook": 1}
CALLOUT_DAY, CALLOUT_AT = 5, 15 * 60 + 30  # Saturday 15:30, before dinner


def _r(x: float) -> int:
    return int(x + 0.5)


def _money(x: float) -> float:
    return round(round(x * 4) / 4, 2)


# --------------------------------------------------------------------------- #
# Law-derived pay floors
# --------------------------------------------------------------------------- #
def wage_floors(pack: LawPack) -> tuple[float | None, float | None, str | None]:
    """(minimum wage, tipped cash wage, tipped rule id) from the pack; tipped = full minimum if no rule."""
    mins = [float(r.params["dollars_per_hour"]) for r in pack.rules if r.type == LawRuleType.minimum_wage]
    full = max(mins) if mins else None
    tipped = [r for r in pack.rules if r.type == LawRuleType.tipped_minimum_wage]
    if tipped:
        r = max(tipped, key=lambda r: float(r.params["cash_wage_per_hour"]))
        return full, float(r.params["cash_wage_per_hour"]), r.id
    return full, full, None


# --------------------------------------------------------------------------- #
# Demand
# --------------------------------------------------------------------------- #
def hourly_demand(role: str, day: int, s: float, event: bool = True) -> list[tuple[int, bool]]:
    wk = {4: 1.35, 5: 1.35, 6: 1.15}.get(day, 1.0)
    o, c = (x // 60 for x in HOURS[day])
    out: list[tuple[int, bool]] = []
    for h in range(24):
        open_ = o <= h < c
        lunch, after, dinner, late = 11 <= h < 14, 14 <= h < 17, 17 <= h < 21, 21 <= h < c
        n = 0
        if role == "manager_on_duty":
            n = 1 if open_ else 0
        elif role == "server" and open_:
            n = max(1, _r((3.0 if lunch else 1.2 if after else 5.0 if dinner else 1.6) * s * (wk if lunch or dinner else 1)))
        elif role == "bartender" and open_:
            n = max(1, _r(1.0 * s * wk)) if (dinner or late) else (1 if s >= 1 and lunch else 0)
        elif role == "host" and open_:
            n = (1 + (1 if s >= 1 and day in (4, 5) else 0)) if dinner else (1 if lunch else 0)
        elif role == "line_cook" and open_:
            n = max(1, _r((2.0 if lunch else 1.0 if after else 3.0 if dinner else 1.0) * s * (wk if lunch or dinner else 1)))
        elif role == "prep_cook":
            n = max(1, _r(2.0 * s)) if 9 <= h < 11 else (max(1, _r(1.0 * s)) if 15 <= h < 17 else 0)
        elif role == "dishwasher" and open_:
            n = max(1, _r(2.0 * s * wk)) if (dinner or late) else 1
        ev = False
        if event and day == EVENT_DAY and EVENT_START // 60 <= h < EVENT_END // 60 and role in EVENT_EXTRA:
            n, ev = n + EVENT_EXTRA[role], True
        out.append((n, ev))
    return out


def build_demand(s: float):
    from .generator import compress_hourly

    profiles = {(role, day): hourly_demand(role, day, s) for day in range(7) for role in ROLES}
    reqs = compress_hourly(profiles)
    for d in reqs:
        if d.event_id:
            d.event_id = "ev_private_3"
    return reqs


# --------------------------------------------------------------------------- #
# Employees
# --------------------------------------------------------------------------- #
def build_employees(rng: random.Random, n: int, n_mgr: int, demand, floors: tuple, area_code: str) -> list[Employee]:
    full_min, tipped_min, _ = floors
    role_hours = {r: 0.0 for r in ROLES}
    for d in demand:
        role_hours[d.role_id] += d.headcount * (d.end - d.start) / 60
    others = [r for r in ROLES if r != "manager_on_duty"]
    n_other = n - n_mgr
    total = sum(role_hours[r] for r in others)
    quotas = {r: n_other * role_hours[r] / total for r in others}
    alloc = {r: int(quotas[r]) for r in others}
    for r in sorted(others, key=lambda r: (-(quotas[r] - alloc[r]), r))[: n_other - sum(alloc.values())]:
        alloc[r] += 1
    primaries = [r for r in others for _ in range(alloc[r])]
    rng.shuffle(primaries)
    names = rng.sample([f"{f} {l}" for f in FIRST_NAMES for l in LAST_NAMES], n)

    emps: list[Employee] = []
    for i in range(n):
        mgr = i < n_mgr
        primary = "manager_on_duty" if mgr else primaries[i - n_mgr]
        minor_ok = primary in ("server", "host", "dishwasher")
        if mgr:
            age = rng.randint(25, 52)
        elif minor_ok and rng.random() < 0.18:
            age = rng.choice([16, 17])
        else:
            age = rng.randint(18, 24) if rng.random() < 0.55 else rng.randint(25, 58)
        if primary == "bartender" and age < 21:
            age = rng.randint(21, 35)
        dept = ROLES[primary][0]
        trained = [primary]
        pool = [r for r in ROLES if ROLES[r][0] == dept and r != primary and age >= ADULT_ONLY_TRAINING.get(r, 0)]
        rng.shuffle(pool)
        trained += pool[: rng.choice([0, 1, 1, 2])]
        if mgr and rng.random() < 0.5:
            trained.append(rng.choice(["server", "bartender", "line_cook"]))
        status = "full_time" if (mgr or (age >= 18 and rng.random() < 0.25)) else "part_time"
        if primary in ("server", "bartender"):
            wage = rng.uniform(15, 16.5)
        elif primary == "manager_on_duty":
            wage = rng.uniform(22, 28)
        elif primary == "line_cook":
            wage = rng.uniform(17, 21)
        else:
            wage = rng.uniform(15, 17.5)
        min_h, max_h = (32.0, 40.0) if status == "full_time" else (10.0, 28.0)
        avail: list[AvailabilityEntry] = []
        if age < 18 or (status == "part_time" and age <= 22 and rng.random() < 0.5):
            for wd in range(5):
                avail.append(AvailabilityEntry(weekday=wd, start=0, end=900, kind=AvailabilityKind.unavailable,
                                               note="School: not before 15:00 on weekdays."))
        if rng.random() < 0.1:
            wd = rng.randrange(7)
            avail.append(AvailabilityEntry(weekday=wd, start=0, end=1440, kind=AvailabilityKind.preferred_off,
                                           weight_dollars=10.0, note=f"Prefers {DAY_NAMES[wd]}s off."))
        offered = rng.randint(0, 8)
        emps.append(Employee(
            id=f"e{i + 1:03d}",
            name=names[i],
            phone=f"+1{area_code}5550{100 + i % 100}",
            age=age,
            home_department_id=dept,
            trained_role_ids=trained,
            status=EmploymentStatus(status),
            wage_per_hour=_money(wage),
            min_hours_week=min_h,
            max_hours_week=max_h,
            availability=avail,
            hire_date=WEEK_START - timedelta(days=rng.randint(40, 365 * 8)),
            attendance=AttendanceStats(shifts_90d=rng.randint(25, 60), callouts_90d=rng.choice([0, 0, 1, 1, 2, 4]),
                                       callins_offered_90d=offered, callins_accepted_90d=rng.randint(0, offered)),
        ))
    # At least ~10% minors (front of house / dish), so the minor rules always have someone to bite.
    want = max(2, _r(0.1 * n))
    minors = [e for e in emps if e.age < 18]
    pool = [e for e in emps if e.age >= 18 and e.trained_role_ids[0] not in ADULT_ONLY_TRAINING]
    pool.sort(key=lambda e: (sum(r in ADULT_ONLY_TRAINING for r in e.trained_role_ids), e.id))
    for e in pool:
        if len(minors) >= want:
            break
        e.trained_role_ids = [r for r in e.trained_role_ids if r not in ADULT_ONLY_TRAINING]
        e.age = 16 + len(minors) % 2
        e.status, e.min_hours_week, e.max_hours_week = EmploymentStatus.part_time, 10.0, 28.0
        e.availability = [AvailabilityEntry(weekday=wd, start=0, end=900, kind=AvailabilityKind.unavailable,
                                            note="School: not before 15:00 on weekdays.") for wd in range(5)]
        minors.append(e)
    from .generator import _lift_wages

    _lift_wages(emps, full_min)
    apply_tipped_wages(emps, tipped_min)
    return emps


def apply_tipped_wages(emps: list[Employee], tipped_min: float | None) -> None:
    """Everyone trained in a tipped role gets tipped_wage_per_hour = the tipped cash floor (never above
    their regular wage)."""
    for e in emps:
        if any(ROLES.get(r, ("", "", 0, False))[3] for r in e.trained_role_ids):
            tw = tipped_min if tipped_min is not None else e.wage_per_hour
            e.tipped_wage_per_hour = round(min(math.ceil(tw * 100) / 100, e.wage_per_hour), 2)
        else:
            e.tipped_wage_per_hour = None


# --------------------------------------------------------------------------- #
# Constraints, narrative, call-outs
# --------------------------------------------------------------------------- #
def _c(id, kind, params, strength, weight, source, note, applies_to=None) -> Constraint:
    return Constraint(id=id, kind=kind, params=params, strength=strength, weight_dollars=weight,
                      applies_to_employee_ids=applies_to, source=source, status=RuleStatus.confirmed, note=note)


def build_constraints(rng: random.Random, emps: list[Employee]) -> list[Constraint]:
    cs = [
        _c("c_min_shift", ConstraintKind.min_shift_length, {"minutes": 180}, Strength.hard, 0, Source.default,
           "Shifts are at least 3 hours."),
        _c("c_max_shift", ConstraintKind.max_shift_length, {"minutes": 600}, Strength.hard, 0, Source.default,
           "Shifts are at most 10 hours."),
        _c("c_min_rest", ConstraintKind.min_rest_between_shifts, {"minutes": 600}, Strength.soft, 30.0,
           Source.default, "Try to leave 10 hours between a close and the next day's open."),
        _c("c_max_days", ConstraintKind.max_days_per_week, {"days": 5}, Strength.hard, 0, Source.leader,
           "Nobody works more than 5 days a week."),
        _c("c_mod_always", ConstraintKind.always_staffed, {"role_id": "manager_on_duty", "windows": "store_hours"},
           Strength.hard, 0, Source.leader, "A manager on duty whenever we're open."),
        _c("c_min_hours", ConstraintKind.min_hours_week, {}, Strength.soft, 10.0, Source.leader,
           "Give people their minimum hours."),
        _c("c_fair_close", ConstraintKind.fair_spread, {"shift_class": "close", "max_per_employee": 3},
           Strength.soft, 10.0, Source.leader, "Spread closes: at most 3 per person."),
    ]
    servers = [e for e in emps if "server" in e.trained_role_ids and e.home_department_id != "management"]
    a, b = rng.sample(servers, 2)
    cs.append(_c("c_not_together_1", ConstraintKind.not_together, {"employee_ids": [a.id, b.id]}, Strength.soft,
                 25.0, Source.leader, f"{a.name.split()[0]} and {b.name.split()[0]} shouldn't work together."))
    return cs


def _hhmm(m: int) -> str:
    h = m // 60
    return f"{h % 12 or 12}{':%02d' % (m % 60) if m % 60 else ''}{'am' if h < 12 else 'pm'}"


def _hours(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.1f}"


def build_narrative(rng: random.Random, cfg: StoreConfig, messy: bool) -> tuple[str, list, list, list]:
    emps = {e.id: e for e in cfg.employees}
    cap = cfg.budget.weekly_hours_cap
    items: list[tuple[dict, str]] = [
        ({"kind": "store_hours_by_day", "hours": {str(d): list(HOURS[d]) for d in HOURS}},
         f"We're open {_hhmm(HOURS[0][0])} to {_hhmm(HOURS[0][1])} Monday through Thursday, till "
         f"{_hhmm(HOURS[4][1])} Friday and Saturday, and {_hhmm(HOURS[6][1])} on Sunday. Prep starts two hours "
         "before we open."),
        ({"kind": "budget_hours_cap", "value": cap},
         rng.choice([f"The owner gives me {_hours(cap)} hours a week for the whole crew.",
                     f"Labor is {_hours(cap)} hours a week, that's the number."])),
        ({"kind": "overtime_allowed", "value": False}, "No overtime."),
        ({"kind": "always_staffed", "role_id": "manager_on_duty"},
         "There's always a manager on the floor when the doors are open."),
        ({"kind": "max_shifts_per_day", "value": 2},
         "Doubles are normal here: people work lunch, go home, and come back for dinner."),
        ({"kind": "min_shift_length", "minutes": 180}, "Nobody comes in for less than 3 hours."),
        ({"kind": "event", "kind_value": "private_event", "day": EVENT_DAY, "start": EVENT_START,
          "end": EVENT_END, "label": EVENT_LABEL},
         f"{DAY_NAMES[EVENT_DAY]} we've got a private party, a rehearsal dinner for about 40, "
         f"{_hhmm(EVENT_START)} to {_hhmm(EVENT_END)}, so I need two extra servers, a second bartender and "
         "another cook on the line."),
        ({"kind": "peaks", "lunch": [660, 840], "dinner": [1020, 1260], "heavier_days": [4, 5]},
         "Lunch is 11 to 2, dinner rush 5 to 9, and Friday and Saturday nights are way busier."),
    ]
    for c in cfg.constraints:
        if c.kind == ConstraintKind.not_together:
            a, b = (emps[x] for x in c.params["employee_ids"])
            items.append(({"kind": "not_together", "employee_ids": [a.id, b.id]},
                          f"Keep {a.name.split()[0]} and {b.name.split()[0]} off the same shift, trust me."))
    students = [e.id for e in cfg.employees
                if sum(1 for a in e.availability if a.kind == AvailabilityKind.unavailable and a.weekday is not None
                       and a.weekday < 5 and a.end == 900) == 5]
    if students:
        items.append(({"kind": "availability", "employee_ids": students, "weekdays": [0, 1, 2, 3, 4],
                       "start": 0, "end": 900, "availability_kind": "unavailable"},
                      "The high school kids can't come in before 3 on weekdays."))
    omissions: list[dict] = []
    contradictions: list[dict] = []
    if messy:
        omittable = [i for i, (f, _) in enumerate(items) if f["kind"] in
                     ("overtime_allowed", "min_shift_length", "availability", "max_shifts_per_day")]
        for i in sorted(rng.sample(omittable, 2), reverse=True):
            omissions.append(items.pop(i)[0])
        alt = (EVENT_DAY + 1) % 7
        s2 = f"Wait, the party might be {DAY_NAMES[alt]}, I have to check the book."
        contradictions.append({"kind": "event", "fact_value": EVENT_DAY, "contradicting_value": alt, "statement": s2})
        items.append(({"kind": "_contradiction"}, s2))
    text = " ".join(t for _, t in items)
    facts = [f for f, _ in items if f["kind"] != "_contradiction"]
    return text, facts, omissions, contradictions


def food_callouts(rng: random.Random, cfg: StoreConfig, roles=("server", "line_cook")) -> list[CallOut]:
    picked: list[str] = []
    for role in roles:
        cands = [e.id for e in cfg.employees if role in e.trained_role_ids and e.age >= 18
                 and e.home_department_id != "management" and e.id not in picked
                 and not any(a.kind == AvailabilityKind.unavailable and a.weekday == CALLOUT_DAY
                             for a in e.availability)]
        if cands:
            picked.append(rng.choice(cands))
    return [CallOut(employee_id=eid, day=CALLOUT_DAY, reported_at=CALLOUT_AT) for eid in picked]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
AREA = {"IL": "312", "TX": "512", "CA": "415", "WA": "206", "NY": "212"}


def generate_food(seed: int, size: str, difficulty: str, jur: Jurisdiction, school_week: bool | None) -> Scenario:
    from .demo import break_allowance

    key = f"food|{seed}|{size}|{difficulty}|{jur.state}|{jur.city or ''}"
    rng = random.Random(key)
    s = SIZE_SCALE[size]
    demand = build_demand(s)
    need = sum(d.headcount * (d.end - d.start) / 60 for d in demand)
    pack = resolve(jur, on=WEEK_START)
    floors = wage_floors(pack)
    emps = build_employees(rng, SIZE_STAFF[size], SIZE_MANAGERS[size], demand, floors, AREA.get(jur.state, "312"))
    constraints = build_constraints(rng, emps)

    expected: dict = {
        "seed": seed, "size": size, "difficulty": difficulty, "sector": "food",
        "jurisdiction": jur.model_dump(), "infeasible": False, "conflicting_ids": [], "traps": {}, "notes": [],
        "school_week": school_week, "minimum_wage": floors[0], "tipped_cash_wage": floors[1],
        "tipped_rule_id": floors[2],
    }
    if difficulty == "legal_trap":
        boh_minor_pool = [e for e in emps if e.age < 18]
        fry = boh_minor_pool[0]
        fry.age = 15
        fry.trained_role_ids.append("line_cook")
        bar = next((e for e in boh_minor_pool[1:]), None)
        if bar is not None:
            bar.trained_role_ids.append("bartender")
            apply_tipped_wages([bar], floors[1])
        expected["traps"] = {
            "minor_fryer_trained": [fry.id], "minor_alcohol_trained": [bar.id] if bar else [],
            "notes": "A 15-year-old trained on line_cook (tags cooking, fryer) and a minor trained on bartender "
                     "(alcohol_service). Whether law bans them comes from the resolved law pack (WS3).",
        }
    elif difficulty == "infeasible":
        mgrs = [e for e in emps if "manager_on_duty" in e.trained_role_ids]
        keep = mgrs[0]
        for e in mgrs[1:]:
            e.trained_role_ids.remove("manager_on_duty")
            if not e.trained_role_ids:
                e.trained_role_ids.append("server")
                apply_tipped_wages([e], floors[1])
        expected.update(infeasible=True, conflicting_ids=["c_mod_always", f"employee:{keep.id}.max_hours_week"],
                        infeasible_variant="single_manager",
                        infeasible_summary=f"manager_on_duty must be covered every open hour, but only {keep.id} "
                                           f"is trained and can work at most {keep.max_hours_week:g} h.")

    ratio = BUDGET_RATIO.get(difficulty, NORMAL_RATIO)
    cap = float(math.floor(need * ratio * break_allowance(pack)))
    cfg = StoreConfig(
        store=Store(
            id=f"gen-food-{size}-{difficulty}-{seed}".lower(),
            name=f"Restaurant #{100 + (seed * 53) % 900} ({size}/{difficulty})",
            jurisdiction=jur,
            timezone=TIMEZONES.get(jur.state, "America/Chicago"),
            slot_minutes=30,
            week_start=WEEK_START,
            hours=[DayHours(day=d, open=o, close=c) for d, (o, c) in HOURS.items()],
            pre_open_minutes=PRE_OPEN,
            post_close_minutes=POST_CLOSE,
            school_week=school_week,
            sector=Sector.food,
            business_description="Full-service neighborhood restaurant and bar.",
            max_shifts_per_day=2,
        ),
        departments=[Department(id=d, name=n) for d, n in DEPARTMENTS],
        roles=[Role(id=r, department_id=v[0], name=v[1], gap_penalty_per_hour=v[2], tipped=v[3], description=v[4])
               for r, v in ROLES.items()],
        role_tags={k: list(v) for k, v in ROLE_TAGS.items()},
        employees=emps,
        demand=demand,
        events=[Event(id="ev_private_3", kind=EventKind.private_event, day=EVENT_DAY, start=EVENT_START,
                      end=EVENT_END, label=EVENT_LABEL, note="Private party in the back room.")],
        budget=Budget(weekly_hours_cap=cap),
        constraints=constraints,
    )
    narrative, facts, omissions, contradictions = build_narrative(random.Random(key + "|narrative"), cfg,
                                                                  messy=difficulty == "messy")
    history = build_history(random.Random(key + "|history"), cfg)
    callouts = food_callouts(random.Random(key + "|callouts"), cfg)
    expected.update(required_hours=need, budget_ratio=round(ratio, 4), narrative_facts=facts,
                    narrative_omissions=omissions, narrative_contradictions=contradictions,
                    callout_day=CALLOUT_DAY, callout_reported_at=CALLOUT_AT, event_day=EVENT_DAY)
    return Scenario(config=cfg, history=history, narrative=narrative, callout_events=callouts, expected=expected)


# --------------------------------------------------------------------------- #
# Demo restaurant (Chicago)
# --------------------------------------------------------------------------- #
DEMO_RESTAURANT_SEED = 612
# Synthetic: a regional restaurant group (~40 locations). Only used for law thresholds
# (predictive_scheduling.applies_if_employees_over).
DEMO_RESTAURANT_EMPLOYER_COUNT = 3_500
# The call-outs work Saturday dinner: unavailable before 16:00 (so a 15:30 call-out is before their
# shift starts) and a Saturday 16:00-23:00 preference so the weekly solve schedules them.
DEMO_CALLOUT_PREFERRED_ON = (16 * 60, 23 * 60, 15.0)


def build_demo_restaurant() -> Scenario:
    from .demo import locality_sentences

    jur = Jurisdiction(state="IL", city="chicago")
    base = generate_food(DEMO_RESTAURANT_SEED, "M", "normal", jur, True)
    cfg = base.config.model_copy(deep=True)
    st = cfg.store
    st.id = "rest-0612"
    st.name = "Harbor Grill #12, Chicago IL"
    st.business_description = "Full-service neighborhood restaurant and bar, 120 seats; part of a regional group."
    st.employer_employee_count = DEMO_RESTAURANT_EMPLOYER_COUNT
    st.schedule_posted_on = st.week_start - timedelta(days=14)
    emps = cfg.employees

    # The law catch: a 15-year-old listed as fryer-trained (line_cook carries cooking + fryer tags).
    minor = sorted((e for e in emps if e.age < 18), key=lambda e: e.id)[0]
    minor.age = 15
    if "line_cook" not in minor.trained_role_ids:
        minor.trained_role_ids.append("line_cook")

    rng = random.Random("demo-0612")
    callouts = food_callouts(rng, cfg)
    s0, s1, w = DEMO_CALLOUT_PREFERRED_ON
    for c in callouts:
        e = next(x for x in emps if x.id == c.employee_id)
        e.availability += [
            AvailabilityEntry(weekday=CALLOUT_DAY, start=0, end=s0, kind=AvailabilityKind.unavailable,
                              note="Saturdays: not before 4pm."),
            AvailabilityEntry(weekday=CALLOUT_DAY, start=s0, end=s1, kind=AvailabilityKind.preferred_on,
                              weight_dollars=w, note="Likes Saturday dinner."),
        ]

    pack = resolve(jur, on=st.week_start)
    history = build_history(random.Random("demo-0612|history"), cfg)
    narrative, facts, _, _ = build_narrative(random.Random("demo-0612|narrative"), cfg, messy=False)
    extra = locality_sentences(pack, "Chicago")
    first = minor.name.split()[0]
    narrative += ("\n\n" + " ".join(t for _, t in extra) if extra else "") + (
        f" {first} is 15, mostly on {ROLES[minor.trained_role_ids[0]][1].lower()}, and has been helping out on "
        "the fryer when we're slammed.")
    expected = dict(base.expected)
    expected.update(
        narrative_facts=facts,
        law_context=[n for n, _ in extra],
        traps={"minor_fryer_trained": [minor.id]},
        callout_day=CALLOUT_DAY,
        callout_reported_at=CALLOUT_AT,
        demo={"minor_fryer_id": minor.id, "callout_employee_ids": [c.employee_id for c in callouts],
              "event_id": "ev_private_3"},
        notes=[
            "Built by shiftwright_scenarios.food.build_demo_restaurant (seed 612, M, normal, Chicago).",
            f"employer_employee_count={DEMO_RESTAURANT_EMPLOYER_COUNT} is synthetic (a regional restaurant group).",
            "tipped_wage_per_hour = the resolved tipped cash minimum, or the full minimum wage while the pack "
            "has no tipped_minimum_wage rule. Regenerate after WS3 adds one.",
        ],
    )
    return Scenario(config=cfg, history=history, narrative=narrative, callout_events=callouts, expected=expected)
