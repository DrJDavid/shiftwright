"""Corporate demand conversions (packages/scenarios/import_packs/demand/README.md, Specs 0, 2, 3, 4, 5).

Planning conventions, not law: ceil for labor standards, round-half-up for hours, cumulative rounding to
spread a department-day's hours over its window. Exact arithmetic (Fraction). Every requirement is
`source: corporate` with a note naming the file style; replacement is per (role, day) (Spec 0).
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from fractions import Fraction
from typing import Optional

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ALL_DAYS = {"daily", "all", "every day", "everyday", "all days", "mon sun", "mon-sun", "7 days"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def round_half_up(x: Fraction) -> int:
    return math.floor(x + Fraction(1, 2))


def frac(s) -> Fraction:
    return Fraction(str(s).strip().replace(",", "").replace("$", "") or "0")


def spread(n_slots: int, units: int) -> list[int]:
    """Cumulative rounding (flat weights): slot i gets round(N*i/n) - round(N*(i-1)/n). Sums to N exactly."""
    out, prev = [], 0
    for i in range(1, n_slots + 1):
        cur = round_half_up(Fraction(units * i, n_slots))
        out.append(cur - prev)
        prev = cur
    return out


def parse_days(s: str) -> list[int]:
    """'Mon-Fri', 'Fri-Mon' (wraps), 'Sat,Sun', 'Tue/Thu/Sat', 'Mon & Wed', 'Daily', 'All', 'Every day'."""
    n = s.strip().lower()
    if n in ALL_DAYS or _norm(n) in ALL_DAYS:
        return list(range(7))
    days: list[int] = []
    for part in re.split(r"\s*(?:,|/|;|&|\band\b|\s)\s*", n):
        part = part.strip()
        if not part:
            continue
        if "-" in part or "–" in part:
            a, b = re.split(r"[-–]", part, maxsplit=1)
            ia, ib = WEEKDAYS.index(a.strip()[:3]), WEEKDAYS.index(b.strip()[:3])
            days += [(ia + k) % 7 for k in range((ib - ia) % 7 + 1)]
        else:
            if part[:3] not in WEEKDAYS:
                raise ValueError(f"bad day {s!r}")
            days.append(WEEKDAYS.index(part[:3]))
    if not days:
        raise ValueError(f"bad day {s!r}")
    return sorted(set(days))


def looks_like_day_list(s: str) -> bool:
    n = s.strip().lower()
    return n in ALL_DAYS or bool(re.search(r"[a-z]{3}\s*[-–/,&]\s*[a-z]{3}", n))


class Slots:
    """{(role_id, day): {slot_start: headcount}} accumulator -> merged DemandRequirements."""

    def __init__(self, slot: int):
        self.slot = slot
        self.m: dict[tuple[str, int], dict[int, int]] = {}
        self.notes: dict[tuple[str, int], str] = {}

    def add(self, role: str, day: int, start: int, hc: int, note: str = "") -> None:
        if hc <= 0:
            return
        d = self.m.setdefault((role, day), {})
        d[start] = d.get(start, 0) + hc
        self.notes.setdefault((role, day), note)

    def add_window(self, role: str, day: int, start: int, end: int, hc: int, note: str = "") -> None:
        t = start - start % self.slot
        while t < end:
            self.add(role, day, t, hc, note)
            t += self.slot

    def requirements(self) -> list[dict]:
        out = []
        for (role, day), slots in sorted(self.m.items()):
            ts = sorted(t for t, n in slots.items() if n > 0)
            i = 0
            while i < len(ts):
                j = i
                while j + 1 < len(ts) and ts[j + 1] == ts[j] + self.slot and slots[ts[j + 1]] == slots[ts[i]]:
                    j += 1
                out.append({"id": f"fc_{role}_{day}_{ts[i]}", "role_id": role, "day": day, "start": ts[i],
                            "end": ts[j] + self.slot, "headcount": slots[ts[i]], "source": "corporate",
                            "note": self.notes.get((role, day), "")})
                i = j + 1
        return out

    def pairs(self) -> set[tuple[str, int]]:
        return set(self.m)


def replace_corporate(d: dict, reqs: list[dict], pairs: set[tuple[str, int]]) -> None:
    """Spec 0: replace corporate demand only for the (role, day) pairs this import produced."""
    d["demand"] = [x for x in d["demand"]
                   if not (x.get("source") == "corporate" and (x["role_id"], x["day"]) in pairs)] + reqs


def open_hours(d: dict) -> dict[int, tuple[int, int]]:
    return {h["day"]: (h["open"], h["close"]) for h in d["store"]["hours"] if h["close"] > h["open"]}


def week_day(value: str, week_start: date, parse_date, warnings: list[str], row: int) -> Optional[int]:
    """Day name / 0-6 / date -> day index; dates outside the schedule week: warn and skip (None)."""
    n = _norm(value)
    if n[:3] in WEEKDAYS and (len(n) <= 3 or n in ("monday", "tuesday", "wednesday", "thursday", "friday",
                                                     "saturday", "sunday", "tues", "weds", "thur", "thurs")):
        return WEEKDAYS.index(n[:3])
    if n.isdigit() and int(n) <= 6:
        return int(n)
    dt = parse_date(value)
    if not week_start <= dt < week_start + timedelta(days=7):
        warnings.append(f"Row {row}: date {dt.isoformat()} is outside the schedule week starting "
                        f"{week_start.isoformat()}; skipped.")
        return None
    return (dt - week_start).days


def check_plausible(d: dict, reqs: list[dict], warnings: list[str]) -> None:
    trained: dict[str, int] = {}
    for e in d["employees"]:
        for r in e.get("trained_role_ids", []):
            trained[r] = trained.get(r, 0) + 1
    names = {r["id"]: r["name"] for r in d["roles"]}
    flagged = set()
    for r in reqs:
        cap = trained.get(r["role_id"]) or 50
        if r["headcount"] > cap and r["role_id"] not in flagged:
            flagged.add(r["role_id"])
            warnings.append(f"{names.get(r['role_id'], r['role_id'])}: headcount {r['headcount']} is more than "
                            f"{'the ' + str(cap) + ' people trained for it' if trained.get(r['role_id']) else '50'}; "
                            "check the column mapping.")


# --------------------------------------------------------------------------- #
# Spec 3: department daily hours + labor model
# --------------------------------------------------------------------------- #
def labor_hours(d: dict, rows: list[dict], model: list[dict], resolve_role, week_start: date, parse_date,
                warnings: list[str]) -> None:
    """rows: [{dept, day, hours, week_total?}] (long; wide files are melted by the caller)."""
    slot = d["store"]["slot_minutes"]
    oh = open_hours(d)
    out = Slots(slot)
    totals: dict[str, Fraction] = {}
    stated_total: dict[str, Fraction] = {}
    store_total: Optional[Fraction] = None
    for r in rows:
        dept = r["dept"].strip()
        if _norm(dept) in ("total", "store total", "grand total"):
            if r.get("week_total") not in (None, ""):
                store_total = frac(r["week_total"])
            continue
        if r.get("week_total") not in (None, ""):
            stated_total[dept] = frac(r["week_total"])
        hours = frac(r["hours"])
        totals[dept] = totals.get(dept, Fraction(0)) + hours
        day = r["day"]
        if hours <= 0:
            continue
        if day not in oh:
            warnings.append(f"{dept} has {float(hours):g} h on {WEEKDAYS[day].title()}, a closed day; dropped.")
            continue
        o, c = oh[day]
        rows_m = [m for m in model if _norm(m["dept"]) == _norm(dept)]
        if not rows_m:
            dept_ids = [x["id"] for x in d["departments"] if _norm(dept) in (_norm(x["id"]), _norm(x["name"]))]
            only = [x for x in d["roles"] if x["department_id"] in dept_ids]
            if len(only) != 1:
                if not any(f"need a labor model for {dept}" in w for w in warnings):
                    warnings.append(f"Need a labor model for {dept} (how its hours split across roles); skipped.")
                continue
            rows_m = [{"dept": dept, "role": only[0]["name"], "share": 100, "start": None, "end": None}]
        for m in rows_m:
            rid = resolve_role(m["role"])
            role_hours = hours * frac(m["share"]) / 100
            ws = m["start"] if m.get("start") is not None else o
            we = m["end"] if m.get("end") is not None else c
            starts = list(range(ws - ws % slot, we, slot))
            units = round_half_up(role_hours * 60 / slot)
            note = f"labor_hours: {dept} {float(hours):.1f} h, {m['role']} {frac(m['share'])}%"
            for t, n in zip(starts, spread(len(starts), units)):
                out.add(rid, day, t, n, note)
    for dept, want in stated_total.items():
        if abs(totals.get(dept, Fraction(0)) - want) > Fraction(1, 20):
            warnings.append(f"{dept}: days add up to {float(totals.get(dept, 0)):g} h but Week Total says {float(want):g} h.")
    if store_total is not None:
        cap = d["budget"].get("weekly_hours_cap") or 0
        if not cap:
            d["budget"]["weekly_hours_cap"] = float(store_total)
            warnings.append(f"Weekly hours cap set to the file's store total, {float(store_total):g} h.")
        elif abs(Fraction(str(cap)) - store_total) > Fraction(1, 20):
            warnings.append(f"The file's store total is {float(store_total):g} h; your hours cap is {cap:g} h (kept).")
    warnings.append("Corporate hours are payroll hours; treating them as headcount-hours ignores unpaid meal time.")
    reqs = out.requirements()
    check_plausible(d, reqs, warnings)
    replace_corporate(d, reqs, out.pairs())


# --------------------------------------------------------------------------- #
# Spec 4: sales / transactions + labor standards
# --------------------------------------------------------------------------- #
WORKLOAD_DRIVERS = ("cases", "pieces")


def sales(d: dict, rows: list[dict], standards: list[dict], resolve_role, week_start: date, parse_date,
          parse_time, warnings: list[str]) -> None:
    slot = d["store"]["slot_minutes"]
    oh = open_hours(d)
    out = Slots(slot)
    stds = [s for s in standards if s["driver"] not in WORKLOAD_DRIVERS]
    missing_warned = set()
    for i, r in enumerate(rows):
        try:
            day = week_day(r["day"], week_start, parse_date, warnings, i + 2)
            hour = parse_time(r["hour"])
        except (KeyError, ValueError) as e:
            warnings.append(f"Row {i + 2}: {e}; skipped.")
            continue
        if day is None:
            continue
        if day not in oh:
            continue
        o, c = oh[day]
        for st in stds:
            rid = resolve_role(st["role"])
            if st["driver"] == "fixed":
                hc = int(st["min_hc"])
            else:
                raw = r.get(st["driver"])
                if raw in (None, ""):
                    if st["role"] not in missing_warned:
                        missing_warned.add(st["role"])
                        warnings.append(f"No {st['driver']} column for {st['role']}; skipped that role.")
                    continue
                v = frac(raw)
                if not range(max(hour, o), min(hour + 60, c), slot):
                    if v > 0:
                        warnings.append(f"Row {i + 2}: {st['driver']} at {hour // 60:02d}:00 is outside open hours; ignored.")
                    continue
                hc = max(int(st["min_hc"]), min(int(st["max_hc"]), math.ceil(v / frac(st["units_per_staff_hour"]))))
            note = f"sales_forecast: {st['role']} {st['driver']}" + (
                f" / {st['units_per_staff_hour']} per staff hour" if st["driver"] != "fixed" else " (fixed)")
            for t in range(max(hour, o), min(hour + 60, c), slot):
                out.add(rid, day, t, hc, note)
    reqs = out.requirements()
    check_plausible(d, reqs, warnings)
    replace_corporate(d, reqs, out.pairs())


# --------------------------------------------------------------------------- #
# Spec 5: truck workload
# --------------------------------------------------------------------------- #
def workload(d: dict, rows: list[dict], standards: list[dict], resolve_role, week_start: date, parse_date,
             parse_time, warnings: list[str]) -> None:
    slot = d["store"]["slot_minutes"]
    oh = open_hours(d)
    pre = d["store"].get("pre_open_minutes", 0)
    out = Slots(slot)
    events = []
    for i, r in enumerate(rows):
        unit = "cases" if r.get("cases") not in (None, "") else "pieces"
        std = next((s for s in standards if s["driver"] == unit), None)
        if std is None:
            warnings.append(f"Row {i + 2}: no labor standard with driver '{unit}'; import labor standards first. Skipped.")
            continue
        try:
            day = week_day(r["day"], week_start, parse_date, warnings, i + 2)
            arrival = parse_time(r["arrival"])
            amount = frac(r[unit])
        except (KeyError, ValueError) as e:
            warnings.append(f"Row {i + 2}: {e}; skipped.")
            continue
        if day is None or amount <= 0:
            continue
        labor = amount / frac(std["units_per_staff_hour"])
        crew = max(int(std["min_hc"]), min(int(std["max_hc"]), math.ceil(labor / frac(std["max_duration_hours"] or 4))))
        minutes = math.ceil(labor * 60 / crew / slot) * slot
        if day in oh and arrival < oh[day][0] - pre:
            warnings.append(f"Row {i + 2}: truck arrives {arrival // 60:02d}:{arrival % 60:02d}, before the store's "
                            "pre-open window; it can't be staffed until the window starts.")
        rid = resolve_role(std["role"])
        out.add_window(rid, day, arrival, arrival + minutes, crew,
                       f"workload: {float(amount):g} {unit} / {std['units_per_staff_hour']} per staff hour, crew {crew}")
        events.append({"id": f"truck_import_{day}_{arrival}", "kind": "truck", "day": day, "start": arrival,
                       "end": arrival + minutes, "note": f"Truck {r.get('truck_id') or ''} ({float(amount):g} {unit})".strip()})
    reqs = out.requirements()
    check_plausible(d, reqs, warnings)
    replace_corporate(d, reqs, out.pairs())
    days = {e["day"] for e in events}
    d["events"] = [e for e in d["events"] if not (e["kind"] == "truck" and e["day"] in days)] + events
