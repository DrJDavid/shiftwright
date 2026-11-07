"""Store-leader narrative: rambling, partial, nicknames. Template + seeded variation, no LLM.

Returns the text plus the facts it implies (for intake recall scoring). In `messy` mode two
facts are left out (listed as omissions) and one stated fact is later contradicted.
"""
from __future__ import annotations

import random

from shiftwright_contracts.models import AvailabilityKind, ConstraintKind, StoreConfig

from .catalog import DAY_NAMES, NICKNAMES, ROLES


def _hhmm(m: int) -> str:
    h = m // 60
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}" if m % 60 == 0 else f"{h12}:{m % 60:02d}{suffix}"


def _days(days: list[int]) -> str:
    names = [DAY_NAMES[d] + "s" for d in days]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _short(name: str) -> str:
    first, last = name.split(" ", 1)
    return f"{first} {last[0]}."


FILLER = [
    "Honestly, Q4 is always a zoo here.",
    "We just got through a remodel, so people are still finding stuff.",
    "Parking lot's been a mess since they repaved half of it.",
    "Corporate keeps changing the planogram on us, but whatever.",
    "Most of the team's been here a while, which helps.",
    "Weekends are where it gets real.",
    "I've been doing this schedule by hand in a spreadsheet, which is why you're here.",
]


def _hours(x: float) -> str:
    """1394 -> "1,394", 1393.5 -> "1,393.5": exactly the configured number, never rounded."""
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.1f}"


def build_narrative(
    rng: random.Random, cfg: StoreConfig, trucks: list[int], messy: bool = False
) -> tuple[str, list[dict], list[dict], list[dict]]:
    emps = {e.id: e for e in cfg.employees}
    nick = {d: rng.choice(v) for d, v in NICKNAMES.items()}
    h = cfg.store.hours[0]
    cap = cfg.budget.weekly_hours_cap

    items: list[tuple[dict, str]] = []  # (fact, sentence)
    items.append(({"kind": "store_hours", "days": [x.day for x in cfg.store.hours], "open": h.open, "close": h.close},
                  rng.choice([f"We're open {_hhmm(h.open)} to {_hhmm(h.close)}, seven days.",
                              f"Doors open at {_hhmm(h.open)}, close at {_hhmm(h.close)}, every day of the week."])))
    items.append(({"kind": "budget_hours_cap", "value": cap},
                  rng.choice([f"Corporate gave us {_hours(cap)} hours for the week and that's a hard number.",
                              f"Payroll is {_hours(cap)} hours this week. Can't go over without my DM signing off."])))
    items.append(({"kind": "overtime_allowed", "value": False},
                  rng.choice(["No overtime, period.", "Nobody goes into overtime unless I approve it, and I won't."])))
    items.append(({"kind": "truck", "days": trucks, "start": 240, "end": 600},
                  rng.choice([f"Trucks come {_days(trucks)}, unload starts at 4am and should be done by 10.",
                              f"We get freight {_days(trucks)}. {nick['receiving'].capitalize()} starts at 4 in the "
                              "morning on those days, wrapped by 10."])))
    items.append(({"kind": "always_staffed", "role_id": "leader_on_duty"},
                  rng.choice([f"There always has to be a leader on duty when we're open, one of {nick['leadership']}.",
                              "Never leave the building without an LOD. Ever."])))
    for c in cfg.constraints:
        if c.kind == ConstraintKind.min_shift_length:
            items.append(({"kind": "min_shift_length", "minutes": c.params["minutes"]},
                          f"Shifts are at least {c.params['minutes'] // 60} hours, nobody comes in for a 2-hour shift."))
        elif c.kind == ConstraintKind.max_shift_length:
            items.append(({"kind": "max_shift_length", "minutes": c.params["minutes"]},
                          f"And nobody does more than {c.params['minutes'] // 60} hours in a day."))
        elif c.kind == ConstraintKind.min_rest_between_shifts:
            items.append(({"kind": "min_rest_between_shifts", "minutes": c.params["minutes"], "strength": "soft"},
                          "I hate clopens. Try to give people 10 hours between a close and an open."))
        elif c.kind == ConstraintKind.not_together:
            a, b = (emps[x] for x in c.params["employee_ids"])
            items.append(({"kind": "not_together", "employee_ids": [a.id, b.id]},
                          rng.choice([f"Oh, and {_short(a.name)} and {_short(b.name)} can't be on together. Long story.",
                                      f"Keep {_short(a.name)} and {_short(b.name)} on different shifts if you can, "
                                      "they don't get along."])))
        elif c.kind == ConstraintKind.preferred_role and c.id == "c_pref_role_1":
            e = emps[c.params["employee_id"]]
            items.append(({"kind": "preferred_role", "employee_id": e.id, "role_id": c.params["role_id"]},
                          f"{_short(e.name)} likes being on {ROLES[c.params['role_id']][1].lower()}, "
                          "put them there when you can."))
    students = [e.id for e in cfg.employees
                if sum(1 for a in e.availability if a.kind == AvailabilityKind.unavailable and a.weekday is not None
                       and a.weekday < 5 and a.end == 900) == 5]
    if students:
        items.append(({"kind": "availability", "employee_ids": students, "weekdays": [0, 1, 2, 3, 4],
                       "start": 0, "end": 900, "availability_kind": "unavailable"},
                      "The high schoolers and the college kids can't come in before 3 on weekdays."))
    others = [e for e in cfg.employees if e.home_department_id != "leadership"]
    star = rng.choice(others)
    items.append(({"kind": "unmodeled", "employee_id": star.id, "text": "great with customers"},
                  f"{_short(star.name)} is the best we've got with customers, honestly."))

    omissions: list[dict] = []
    contradictions: list[dict] = []
    if messy:
        omittable = [i for i, (f, _) in enumerate(items) if f["kind"] in
                     ("overtime_allowed", "max_shift_length", "min_rest_between_shifts", "preferred_role",
                      "availability", "min_shift_length")]
        drop = sorted(rng.sample(omittable, 2), reverse=True)
        for i in drop:
            omissions.append(items.pop(i)[0])
        which = rng.choice(["truck", "budget_hours_cap"])
        if which == "truck":
            other = [d for d in range(7) if d not in trucks]
            alt = sorted(rng.sample(other, 1) + trucks[1:])
            s2 = f"Wait, no, trucks moved to {_days(alt)} last month I think."
            contradictions.append({"kind": "truck", "fact_value": trucks, "contradicting_value": alt, "statement": s2})
        else:
            alt_cap = round(cap * rng.choice([0.9, 1.1]) / 10) * 10
            s2 = f"Actually I think the hours number is more like {_hours(alt_cap)}, don't quote me."
            contradictions.append({"kind": "budget_hours_cap", "fact_value": cap, "contradicting_value": alt_cap,
                                   "statement": s2})

    facts = [f for f, _ in items]
    sentences = [s for _, s in items]
    rng.shuffle(sentences)
    for f in rng.sample(FILLER, 3):
        sentences.insert(rng.randrange(len(sentences) + 1), f)
    if contradictions:
        sentences.append(contradictions[0]["statement"])  # late in the ramble, after the first statement
    intro = rng.choice([
        f"So this is {cfg.store.name}.",
        f"Okay, quick rundown on {cfg.store.name}.",
        f"Alright, here's the deal with {cfg.store.name}.",
    ])
    depts = ", ".join(nick[d.id] for d in cfg.departments if d.id != "leadership")
    text = " ".join([intro, f"We've got {depts}, plus {nick['leadership']}."] + sentences)
    return text, facts, omissions, contradictions
