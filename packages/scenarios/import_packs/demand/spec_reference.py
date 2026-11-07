"""Reference implementation of the demand conversions specified in demand/README.md.

Pure functions, exact arithmetic (Fraction). The xfail tests compare the API's resulting demand with
these, slot by slot, so WS6 can implement the spec in apps/api and turn them green. WS6 should
re-implement (not import) this; it lives here only to pin the expected numbers.

A "slot map" is {(role_id, day, slot_start_minute): headcount} with headcount > 0, at the store's
slot length. role_id = slug of the role name, exactly like the importer's Resolver.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction

SlotMap = dict[tuple[str, int, int], int]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def round_half_up(x: Fraction) -> int:
    return math.floor(x + Fraction(1, 2))


def spread(weights: list[Fraction], total_units: int) -> list[int]:
    """Cumulative rounding: unit i gets round(N*cum_i/W) - round(N*cum_{i-1}/W). Sums to N exactly,
    spreads remainders evenly, is deterministic, and follows the weights' shape."""
    w_total = sum(weights)
    if total_units <= 0 or w_total <= 0:
        return [0] * len(weights)
    out, cum, prev = [], Fraction(0), 0
    for w in weights:
        cum += w
        cur = round_half_up(Fraction(total_units) * cum / w_total)
        out.append(cur - prev)
        prev = cur
    return out


def add(m: SlotMap, role: str, day: int, start: int, hc: int) -> None:
    if hc > 0:
        m[(role, day, start)] = m.get((role, day, start), 0) + hc


# --------------------------------------------------------------------------- #
# 3. dept_daily_hours: department x day -> budgeted hours
# --------------------------------------------------------------------------- #
def labor_hours_to_slots(dept_hours: dict[tuple[str, int], Fraction],
                         model: list[dict], open_hours: dict[int, tuple[int, int]], slot: int,
                         weights: dict[tuple[str, int, int], Fraction] | None = None) -> SlotMap:
    """dept_hours[(dept_norm, day)] = hours. model rows: {dept, role, share (percent), start, end}
    (start/end in minutes or None = store open/close that day). weights (optional, v2): per
    (role_id, day, slot) weight; default flat."""
    out: SlotMap = {}
    for (dept, day), hours in sorted(dept_hours.items()):
        if hours <= 0 or day not in open_hours:
            continue
        o, c = open_hours[day]
        for row in [r for r in model if slug(r["dept"]) == slug(dept)]:
            rid = slug(row["role"])
            role_hours = hours * Fraction(row["share"]) / 100
            ws, we = row.get("start") if row.get("start") is not None else o, row.get("end") if row.get("end") is not None else c
            starts = list(range(ws, we, slot))
            units = round_half_up(role_hours * 60 / slot)
            wts = [(weights or {}).get((rid, day, s), Fraction(1)) for s in starts]
            for s, n in zip(starts, spread(wts, units)):
                add(out, rid, day, s, n)
    return out


# --------------------------------------------------------------------------- #
# 4. sales_driven: hourly drivers + labor standards
# --------------------------------------------------------------------------- #
def sales_to_slots(rows: list[dict], standards: list[dict], open_hours: dict[int, tuple[int, int]],
                   slot: int) -> SlotMap:
    """rows: {day, hour (minute of hour start), transactions, sales, online_orders}.
    standards: {role, driver, per (units per staff-hour), min, max}; driver in
    transactions | sales | online_orders | fixed (cases rows are ignored here)."""
    out: SlotMap = {}
    for r in rows:
        if r["day"] not in open_hours:
            continue
        o, c = open_hours[r["day"]]
        for st in standards:
            if st["driver"] == "cases":
                continue
            if st["driver"] == "fixed":
                hc = st["min"]
            else:
                v = Fraction(str(r[st["driver"]]))
                hc = max(st["min"], min(st["max"], math.ceil(v / Fraction(str(st["per"])))))
            for s in range(max(r["hour"], o), min(r["hour"] + 60, c), slot):
                add(out, slug(st["role"]), r["day"], s, hc)
    return out


# --------------------------------------------------------------------------- #
# 5. workload_units: truck cases + unload standard
# --------------------------------------------------------------------------- #
def truck_plan(cases: int, per: float, crew_min: int, crew_max: int, max_hours: float, slot: int) -> tuple[int, int]:
    """-> (crew, duration_minutes). labor = cases/per; crew = clamp(ceil(labor/max_hours)); duration =
    labor/crew rounded UP to the slot."""
    labor = Fraction(cases) / Fraction(str(per))
    crew = max(crew_min, min(crew_max, math.ceil(labor / Fraction(str(max_hours)))))
    minutes = labor * 60 / crew
    return crew, math.ceil(minutes / slot) * slot


def workload_to_slots(trucks: list[dict], std: dict, slot: int) -> SlotMap:
    """trucks: {day, arrival (minutes), cases}. std: {role, per, min, max, max_hours}. Overlapping
    trucks on a day add up."""
    out: SlotMap = {}
    for t in trucks:
        crew, dur = truck_plan(t["cases"], std["per"], std["min"], std["max"], std["max_hours"], slot)
        for s in range(t["arrival"], t["arrival"] + dur, slot):
            add(out, slug(std["role"]), t["day"], s, crew)
    return out


# --------------------------------------------------------------------------- #
# 2. windowed_roles: day ranges
# --------------------------------------------------------------------------- #
_D = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_days(s: str) -> list[int]:
    """'Mon-Fri', 'Sat,Sun', 'Tue/Thu/Sat', 'Daily', 'Mon-Sun', 'Fri-Mon' (wraps)."""
    n = s.strip().lower()
    if n in ("daily", "all", "every day", "mon-sun"):
        return list(range(7))
    days: list[int] = []
    for part in re.split(r"[,/;& ]+", n):
        if not part:
            continue
        if "-" in part:
            a, b = (_D.index(x[:3]) for x in part.split("-", 1))
            days += [(a + k) % 7 for k in range((b - a) % 7 + 1)]
        else:
            days.append(_D.index(part[:3]))
    return sorted(set(days))


def windows_to_slots(rows: list[dict], slot: int) -> SlotMap:
    """rows: {role, days (str), start, end (minutes, end may be <= start = overnight), headcount}."""
    out: SlotMap = {}
    for r in rows:
        end = r["end"] if r["end"] > r["start"] else r["end"] + 1440
        for d in parse_days(r["days"]):
            for s in range(r["start"], end, slot):
                add(out, slug(r["role"]), d, s, r["headcount"])
    return out


def config_slot_map(cfg: dict) -> SlotMap:
    """Expand a StoreConfig's demand to a slot map (overlapping requirements add up, as the validator counts them)."""
    slot = cfg["store"]["slot_minutes"]
    out: SlotMap = {}
    for d in cfg["demand"]:
        s0 = d["start"] - d["start"] % slot
        for s in range(s0, d["end"], slot):
            add(out, d["role_id"], d["day"], s, d["headcount"])
    return out
