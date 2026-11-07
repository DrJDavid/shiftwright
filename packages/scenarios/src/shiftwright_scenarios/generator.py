"""generate(seed, size, difficulty, jurisdiction) -> Scenario. Deterministic per arguments.

Every random draw comes from random.Random(<string seed>) (SHA-512 seeded, stable across
processes). Never iterate sets; always lists or sorted keys.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Literal

from shiftwright_contracts.models import (
    AttendanceStats,
    AvailabilityEntry,
    AvailabilityKind,
    Budget,
    Constraint,
    ConstraintKind,
    DayHours,
    DemandRequirement,
    DemandSource,
    Department,
    Employee,
    EmploymentStatus,
    Event,
    EventKind,
    Jurisdiction,
    Role,
    RuleStatus,
    Source,
    Store,
    StoreConfig,
    Strength,
)

from .callouts import default_callouts
from .catalog import (
    DAY_NAMES,
    DEPARTMENTS,
    FIRST_NAMES,
    LAST_NAMES,
    ROLE_TAGS,
    ROLES,
    SMALL_ROLES,
    TIMEZONES,
)
from .history import build_history
from .models import Scenario
from .narrative import build_narrative

Size = Literal["S", "M", "L"]
Difficulty = Literal["easy", "normal", "tight", "legal_trap", "infeasible", "messy"]
DIFFICULTIES: list[str] = ["easy", "normal", "tight", "legal_trap", "infeasible", "messy"]

WEEK_START = date(2026, 11, 9)  # a Monday
OPEN, CLOSE = 8 * 60, 22 * 60   # 08:00-22:00 every day = 98 open hours/week
PRE_OPEN, POST_CLOSE = 240, 60  # trucks start 04:00
TRUCK_START, TRUCK_END = 4 * 60, 10 * 60

SIZE_STAFF = {"S": 27, "M": 60, "L": 120}
SIZE_LEADERS = {"S": 4, "M": 6, "L": 10}
SIZE_SCALE = {"S": 0.42, "M": 1.0, "L": 2.0}
TRUCK_DAYS = {"S": [2, 5], "M": [1, 3, 5], "L": [0, 2, 3, 5]}
# weekly_hours_cap = required_hours * ratio
BUDGET_RATIO = {"easy": 1.2, "tight": 0.9}
NORMAL_RATIO = 1 / 1.05  # full coverage needs ~105% of the cap
TRUCK_ROLES = ("truck_unload", "backroom", "pit_operator")

AREA_CODES = ["512", "737", "210", "214", "713"]


def _r(x: float) -> int:
    return int(x + 0.5)


def _parse_jurisdiction(j: str | Jurisdiction) -> Jurisdiction:
    if isinstance(j, Jurisdiction):
        return j
    state, _, city = j.partition("/")
    return Jurisdiction(state=state.strip().upper(), city=city.strip().lower() or None)


# --------------------------------------------------------------------------- #
# Demand
# --------------------------------------------------------------------------- #
def hourly_demand(role: str, day: int, s: float, trucks: list[int]) -> list[tuple[int, bool]]:
    """24 (headcount, is_event) pairs for one role/day. Hours are local clock hours."""
    wk = {4: 1.15, 5: 1.3, 6: 1.2}.get(day, 1.0)
    truck = day in trucks
    out: list[tuple[int, bool]] = []
    for h in range(24):
        open_ = 8 <= h < 22
        n, ev = 0, False
        if role == "leader_on_duty":
            n = 1 if open_ else 0
        elif role == "guest_service_desk":
            if open_:
                n = 1 + (1 if s >= 1 and day >= 4 and 11 <= h < 19 else 0)
        elif role == "cashier":
            if open_:
                base = 1.2 if h < 11 else 3.5 if h < 14 else 2.2 if h < 16 else 3.5 if h < 19 else 2.0
                n = max(1, _r(base * s * wk))
        elif role == "drive_up":
            if 9 <= h < 21:
                base = 2.0 if (11 <= h < 14 or 16 <= h < 19) else 1.0
                n = max(1, _r(base * s * wk))
        elif role == "cart_attendant":
            if 10 <= h < 20:
                n = max(1, _r(0.8 * s * wk))
        elif role in ("softlines", "hardlines"):
            if 9 <= h < 21:
                n = max(1, _r(1.0 * s * wk))
        elif role == "fitting_room":
            if 10 <= h < 21:
                n = max(1, _r(0.8 * s * wk))
        elif role == "grocery_stock":
            if 6 <= h < 12:
                n = max(1, _r(2.0 * s))
            elif 12 <= h < 20:
                n = 1
        elif role == "order_picker":
            if 7 <= h < 13:
                n = max(1, _r(3.0 * s))
            elif 13 <= h < 19:
                n = max(1, _r(1.0 * s))
        elif role == "ap_specialist":
            if 10 <= h < 22:
                n = 1 + (1 if s >= 2 and day >= 5 and 12 <= h < 20 else 0)
        elif role == "truck_unload":
            if truck and 4 <= h < 10:
                n, ev = max(2, _r(4.0 * s)), True
        elif role == "backroom":
            if truck and 7 <= h < 13:
                n, ev = max(1, _r(2.0 * s)), True
            elif not truck and s >= 1 and 8 <= h < 12:
                n = 1
        elif role == "pit_operator":
            if truck and 4 <= h < 9:
                n, ev = (1 if s < 2 else 2), True
        out.append((n, ev))
    return out


def compress_hourly(profiles: dict[tuple[str, int], list[tuple[int, bool]]]) -> list[DemandRequirement]:
    """(role, day) -> 24 (headcount, is_event) pairs  =>  non-overlapping DemandRequirements."""
    reqs: list[DemandRequirement] = []
    for role, day in sorted(profiles, key=lambda k: (k[1], k[0])):
        prof = profiles[(role, day)]
        h = 0
        while h < 24:
            n, ev = prof[h]
            if n == 0:
                h += 1
                continue
            e = h
            while e < 24 and prof[e] == (n, ev):
                e += 1
            reqs.append(
                DemandRequirement(
                    id=f"d_{role}_{day}_{h * 60:04d}",
                    role_id=role,
                    day=day,
                    start=h * 60,
                    end=e * 60,
                    headcount=n,
                    source=DemandSource.event if ev else DemandSource.corporate,
                    event_id=f"ev_truck_{day}" if ev else None,
                )
            )
            h = e
    return reqs


def hourly_profiles(role_ids: list[str], s: float, trucks: list[int]) -> dict[tuple[str, int], list[tuple[int, bool]]]:
    return {(role, day): hourly_demand(role, day, s, trucks) for day in range(7) for role in role_ids}


def build_demand(role_ids: list[str], s: float, trucks: list[int]) -> list[DemandRequirement]:
    return compress_hourly(hourly_profiles(role_ids, s, trucks))


def required_hours(demand: list[DemandRequirement]) -> float:
    return sum(d.headcount * (d.end - d.start) / 60 for d in demand)


# --------------------------------------------------------------------------- #
# Employees
# --------------------------------------------------------------------------- #
def _age(rng: random.Random) -> int:
    x = rng.random()
    if x < 0.6:
        return rng.randint(18, 29)
    if x < 0.85:
        return rng.randint(30, 45)
    return rng.randint(46, 64)


def _money(x: float) -> float:
    return round(round(x * 4) / 4, 2)


def build_employees(
    rng: random.Random,
    n: int,
    n_leaders: int,
    role_ids: list[str],
    demand: list[DemandRequirement],
) -> list[Employee]:
    role_hours = {r: 0.0 for r in role_ids}
    peak = {r: 0 for r in role_ids}
    for d in demand:
        role_hours[d.role_id] += d.headcount * (d.end - d.start) / 60
        peak[d.role_id] = max(peak[d.role_id], d.headcount)
    dept_ids = [d for d, _ in DEPARTMENTS if d != "leadership" and any(ROLES[r][0] == d for r in role_ids)]
    dept_hours = {d: sum(role_hours[r] for r in role_ids if ROLES[r][0] == d) for d in dept_ids}

    n_other = n - n_leaders
    # Home departments by largest remainder on demand hours.
    total = sum(dept_hours.values())
    quotas = {d: n_other * dept_hours[d] / total for d in dept_ids}
    alloc = {d: int(quotas[d]) for d in dept_ids}
    for d in sorted(dept_ids, key=lambda d: (-(quotas[d] - alloc[d]), d))[: n_other - sum(alloc.values())]:
        alloc[d] += 1
    homes = [d for d in dept_ids for _ in range(alloc[d])]
    rng.shuffle(homes)

    # Status mix: ~30% FT overall (leaders are FT), 10% seasonal, rest PT; ~8% minors.
    n_ft = max(0, _r(0.3 * n) - n_leaders)
    n_seasonal = _r(0.1 * n)
    statuses = ["full_time"] * n_ft + ["seasonal"] * n_seasonal + ["part_time"] * (n_other - n_ft - n_seasonal)
    rng.shuffle(statuses)
    non_ft = [i for i, s in enumerate(statuses) if s != "full_time"]
    minor_idx = sorted(rng.sample(non_ft, max(1, _r(0.08 * n))))

    names = rng.sample([f"{f} {l}" for f in FIRST_NAMES for l in LAST_NAMES], n)

    def eligible(roles: list[str], age: int) -> list[str]:
        return [r for r in roles if ROLES[r][2] <= age]

    people: list[dict] = []
    for i in range(n):
        leader = i < n_leaders
        j = i - n_leaders
        status = "full_time" if leader else statuses[j]
        age = rng.randint(26, 55) if leader else (rng.choice([16, 17]) if j in minor_idx else _age(rng))
        home = "leadership" if leader else homes[j]
        if leader:
            trained = ["leader_on_duty"]
            if rng.random() < 0.6:
                trained.append(rng.choice([r for r in role_ids if r != "leader_on_duty" and ROLES[r][2] <= age]))
        else:
            dept_roles = eligible([r for r in role_ids if ROLES[r][0] == home], age)
            primary = rng.choices(dept_roles, weights=[role_hours[r] + 1 for r in dept_roles])[0]
            trained = [primary]
            extra = [r for r in dept_roles if r != primary]
            rng.shuffle(extra)
            trained += extra[: rng.choice([0, 1, 1, 2])]
            if rng.random() < 0.25:
                other = eligible([r for r in role_ids if ROLES[r][0] not in (home, "leadership")], age)
                if other:
                    trained.append(rng.choice(other))
        people.append({"i": i, "leader": leader, "status": status, "age": age, "home": home, "trained": trained})

    # Every demanded role needs enough trained people (not counting leaders).
    for r in role_ids:
        if r == "leader_on_duty":
            continue
        need = max(2, math.ceil(peak[r] * 1.5)) if r != "pit_operator" else max(2, peak[r] + 1)
        have = [p for p in people if r in p["trained"] and not p["leader"]]
        cands = [p for p in people if not p["leader"] and r not in p["trained"] and p["age"] >= ROLES[r][2]]
        rng.shuffle(cands)
        cands.sort(key=lambda p: (p["home"] != ROLES[r][0], len(p["trained"])))
        for p in cands[: max(0, need - len(have))]:
            p["trained"].append(r)

    emps: list[Employee] = []
    for p in people:
        i, status, age = p["i"], p["status"], p["age"]
        if p["leader"]:
            wage = _money(rng.uniform(24, 30))
        elif age < 18:
            wage = _money(rng.uniform(15, 16))
        else:
            bump = 0.75 if any(r in p["trained"] for r in ("pit_operator", "truck_unload")) else 0.0
            wage = _money(min(22.0, rng.uniform(15, 20.5) + bump))
        min_h, max_h = {"full_time": (32.0, 40.0), "part_time": (12.0, 29.0), "seasonal": (0.0, 24.0)}[status]
        avail: list[AvailabilityEntry] = []
        student = age < 18 or (status != "full_time" and age <= 22 and rng.random() < 0.5)
        if student:
            for wd in range(5):
                avail.append(AvailabilityEntry(weekday=wd, start=0, end=900, kind=AvailabilityKind.unavailable,
                                               note="School: not before 15:00 on weekdays."))
        if not p["leader"] and rng.random() < 0.12:
            avail.append(AvailabilityEntry(weekday=6, start=0, end=720, kind=AvailabilityKind.unavailable,
                                           note="No Sundays before noon."))
        if rng.random() < 0.1:
            wd = rng.randrange(7)
            avail.append(AvailabilityEntry(weekday=wd, start=0, end=1440, kind=AvailabilityKind.preferred_off,
                                           weight_dollars=rng.choice([5.0, 10.0, 15.0]),
                                           note=f"Prefers {DAY_NAMES[wd]}s off."))
        shifts = {"full_time": rng.randint(55, 65), "part_time": rng.randint(28, 45), "seasonal": rng.randint(8, 25)}[status]
        offered = rng.randint(0, 8)
        att = AttendanceStats(
            shifts_90d=shifts,
            callouts_90d=rng.choice([0, 0, 1, 1, 2, 3, 5]),
            callins_offered_90d=offered,
            callins_accepted_90d=rng.randint(0, offered),
        )
        hire = WEEK_START - timedelta(days=rng.randint(20, 70) if status == "seasonal" else rng.randint(60, 365 * 12))
        if age < 18:
            hire = max(hire, WEEK_START - timedelta(days=rng.randint(30, 500)))
        emps.append(
            Employee(
                id=f"e{i + 1:03d}",
                name=names[i],
                phone=f"+1{AREA_CODES[i // 100]}5550{100 + i % 100}",
                age=age,
                home_department_id=p["home"],
                trained_role_ids=p["trained"],
                status=EmploymentStatus(status),
                wage_per_hour=wage,
                min_hours_week=min_h,
                max_hours_week=max_h,
                availability=avail,
                hire_date=hire,
                attendance=att,
            )
        )
    return emps


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #
def _c(id: str, kind: ConstraintKind, params: dict, strength: Strength, weight: float, source: Source, note: str,
       applies_to: list[str] | None = None) -> Constraint:
    return Constraint(id=id, kind=kind, params=params, strength=strength, weight_dollars=weight,
                      applies_to_employee_ids=applies_to, source=source, status=RuleStatus.confirmed, note=note)


def build_constraints(rng: random.Random, emps: list[Employee]) -> list[Constraint]:
    cs = [
        _c("c_min_shift", ConstraintKind.min_shift_length, {"minutes": 240}, Strength.hard, 0, Source.default,
           "Shifts are at least 4 hours."),
        _c("c_max_shift", ConstraintKind.max_shift_length, {"minutes": 600}, Strength.hard, 0, Source.default,
           "Shifts are at most 10 hours."),
        _c("c_min_rest", ConstraintKind.min_rest_between_shifts, {"minutes": 600}, Strength.soft, 30.0, Source.default,
           "Try to leave 10 hours between shifts (avoid clopens)."),
        _c("c_max_days", ConstraintKind.max_days_per_week, {"days": 5}, Strength.hard, 0, Source.corporate,
           "Nobody works more than 5 days a week."),
        _c("c_lod_always", ConstraintKind.always_staffed, {"role_id": "leader_on_duty", "windows": "store_hours"},
           Strength.hard, 0, Source.corporate, "A leader on duty whenever the store is open."),
        _c("c_min_hours", ConstraintKind.min_hours_week, {}, Strength.soft, 10.0, Source.corporate,
           "Give people their minimum hours."),
        _c("c_fair_close", ConstraintKind.fair_spread, {"shift_class": "close", "max_per_employee": 3}, Strength.soft,
           10.0, Source.leader, "Spread closes: at most 3 per person."),
        _c("c_fair_open", ConstraintKind.fair_spread, {"shift_class": "open", "max_per_employee": 3}, Strength.soft,
           10.0, Source.leader, "Spread opens: at most 3 per person."),
    ]
    others = [e for e in emps if e.home_department_id != "leadership"]
    by_dept: dict[str, list[Employee]] = {}
    for e in others:
        by_dept.setdefault(e.home_department_id, []).append(e)
    big = max(sorted(by_dept), key=lambda d: len(by_dept[d]))
    a, b = rng.sample(by_dept[big], 2)
    cs.append(_c("c_not_together_1", ConstraintKind.not_together, {"employee_ids": [a.id, b.id]}, Strength.soft, 25.0,
                 Source.leader, f"{a.name.split()[0]} and {b.name.split()[0]} shouldn't work together."))
    multi = [e for e in others if len(e.trained_role_ids) >= 2]
    for k, e in enumerate(rng.sample(multi, min(2, len(multi)))):
        cs.append(_c(f"c_pref_role_{k + 1}", ConstraintKind.preferred_role,
                     {"employee_id": e.id, "role_id": e.trained_role_ids[0]}, Strength.soft, 5.0, Source.leader,
                     f"{e.name.split()[0]} prefers {ROLES[e.trained_role_ids[0]][1]}."))
    return cs


# --------------------------------------------------------------------------- #
# Difficulty tweaks
# --------------------------------------------------------------------------- #
def _apply_legal_trap(rng: random.Random, emps: list[Employee]) -> dict:
    minors = [e for e in emps if e.age < 18]
    pit = rng.sample(minors, min(2, len(minors)))
    for e in pit:
        e.trained_role_ids.append("pit_operator")
    adults = [e for e in emps if e.age >= 18 and e.home_department_id != "leadership"
              and not any(a.kind == AvailabilityKind.unavailable for a in e.availability)]
    clopen = rng.sample(adults, min(3, len(adults)))
    for e in clopen:
        d = rng.randrange(6)
        e.availability += [
            AvailabilityEntry(weekday=d, start=0, end=960, kind=AvailabilityKind.unavailable,
                              note=f"{DAY_NAMES[d]}: evenings only (after 16:00)."),
            AvailabilityEntry(weekday=d + 1, start=780, end=1440, kind=AvailabilityKind.unavailable,
                              note=f"{DAY_NAMES[d + 1]}: mornings only (until 13:00)."),
        ]
    return {
        "minor_pit_trained": [e.id for e in pit],
        "clopen_prone": [e.id for e in clopen],
        "notes": "Minors trained on PIT must never be scheduled on pit_operator. Clopen-prone employees can "
                 "only close one day and open the next. Meal/rest-break traps depend on the jurisdiction's law pack "
                 "(use CA for those).",
    }


def _apply_infeasible(rng: random.Random, emps: list[Employee]) -> tuple[list[str], str, str]:
    leaders = [e for e in emps if "leader_on_duty" in e.trained_role_ids]
    variant = rng.choice(["single_leader", "leader_blackout"])
    if variant == "single_leader":
        keep = leaders[0]
        for e in leaders[1:]:
            e.trained_role_ids.remove("leader_on_duty")
            if not e.trained_role_ids:
                e.trained_role_ids.append("guest_service_desk")
        ids = ["c_lod_always", f"employee:{keep.id}.max_hours_week"]
        summary = (f"leader_on_duty must be covered all 98 open hours, but only {keep.id} is trained and can work "
                   f"at most {keep.max_hours_week:g} h (and 5 days of at most 10 h).")
        return ids, variant, summary
    d = rng.randrange(7)
    for e in leaders:
        e.availability.append(AvailabilityEntry(weekday=d, start=480, end=600, kind=AvailabilityKind.unavailable,
                                                note=f"District meeting off-site {DAY_NAMES[d]} 08:00-10:00."))
    ids = ["c_lod_always"] + [f"employee:{e.id}.availability" for e in leaders]
    summary = (f"Every leader trained for leader_on_duty is unavailable {DAY_NAMES[d]} 08:00-10:00, "
               "but the store is open and a leader must be on duty.")
    return ids, variant, summary


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def generate(
    seed: int,
    size: Size = "M",
    difficulty: Difficulty = "normal",
    jurisdiction: str | Jurisdiction = "TX",
) -> Scenario:
    if size not in SIZE_STAFF:
        raise ValueError(f"size must be S, M or L, got {size!r}")
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}, got {difficulty!r}")
    jur = _parse_jurisdiction(jurisdiction)
    key = f"{seed}|{size}|{difficulty}|{jur.state}|{jur.city or ''}"
    rng = random.Random(key)

    role_ids = SMALL_ROLES if size == "S" else list(ROLES)
    trucks = TRUCK_DAYS[size]
    s = SIZE_SCALE[size]
    demand = build_demand(role_ids, s, trucks)
    need = required_hours(demand)

    emps = build_employees(rng, SIZE_STAFF[size], SIZE_LEADERS[size], role_ids, demand)
    constraints = build_constraints(rng, emps)

    expected: dict = {
        "seed": seed, "size": size, "difficulty": difficulty,
        "jurisdiction": jur.model_dump(),
        "infeasible": False, "conflicting_ids": [], "traps": {}, "notes": [],
    }
    if difficulty == "legal_trap":
        expected["traps"] = _apply_legal_trap(rng, emps)
    elif difficulty == "infeasible":
        ids, variant, summary = _apply_infeasible(rng, emps)
        expected.update(infeasible=True, conflicting_ids=ids, infeasible_variant=variant, infeasible_summary=summary)

    ratio = BUDGET_RATIO.get(difficulty, NORMAL_RATIO)
    cap = round(need * ratio * 2) / 2

    used_depts = sorted({ROLES[r][0] for r in role_ids}, key=[d for d, _ in DEPARTMENTS].index)
    cfg = StoreConfig(
        store=Store(
            id=f"gen-{size}-{difficulty}-{seed}".lower(),
            name=f"Store #{1000 + (seed * 37) % 9000} ({size}/{difficulty})",
            jurisdiction=jur,
            timezone=TIMEZONES.get(jur.state, "America/Chicago"),
            slot_minutes=30,
            week_start=WEEK_START,
            hours=[DayHours(day=d, open=OPEN, close=CLOSE) for d in range(7)],
            pre_open_minutes=PRE_OPEN,
            post_close_minutes=POST_CLOSE,
        ),
        departments=[Department(id=d, name=n) for d, n in DEPARTMENTS if d in used_depts],
        roles=[Role(id=r, department_id=ROLES[r][0], name=ROLES[r][1], min_age=ROLES[r][2],
                    gap_penalty_per_hour=ROLES[r][3], description=ROLES[r][4]) for r in role_ids],
        role_tags={k: list(v) for k, v in ROLE_TAGS.items() if k in role_ids},
        employees=emps,
        demand=demand,
        events=[Event(id=f"ev_truck_{d}", kind=EventKind.truck, day=d, start=TRUCK_START, end=TRUCK_END,
                      note=f"{DAY_NAMES[d]} truck, 04:00-10:00.") for d in trucks],
        budget=Budget(weekly_hours_cap=cap),
        constraints=constraints,
    )

    narrative, facts, omissions, contradictions = build_narrative(random.Random(key + "|narrative"), cfg, trucks,
                                                                  messy=difficulty == "messy")
    history = build_history(random.Random(key + "|history"), cfg)
    callouts = default_callouts(random.Random(key + "|callouts"), cfg, trucks[-1])
    expected.update(
        required_hours=need,
        budget_ratio=round(ratio, 4),
        truck_days=trucks,
        narrative_facts=facts,
        narrative_omissions=omissions,
        narrative_contradictions=contradictions,
        callout_day=trucks[-1],
    )
    return Scenario(config=cfg, history=history, narrative=narrative, callout_events=callouts, expected=expected)
