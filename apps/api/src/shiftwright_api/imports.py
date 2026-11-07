"""CSV import: parse -> propose column mapping -> ImportPreview -> (leader confirms) -> deterministic commit.

Mapping direction: `proposed_mapping[source_column] = target_field | None` (None = ignore column).
The LLM (when configured) sees ONLY the headers and 5 sample rows. A name-matching heuristic is
always computed first and is the fallback when no LLM is available or its answer is unusable.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from .agent.llm import LLMClient
from .models import ImportPreview

# target field -> (required, synonyms)
TARGETS: dict[str, dict[str, tuple[bool, list[str]]]] = {
    "roster": {
        "employee_id": (True, ["id", "employee id", "emp id", "tm id", "tm_id", "team member id", "badge", "employee number"]),
        "name": (True, ["name", "full name", "employee name", "team member", "tm name"]),
        "first_name": (False, ["first", "first name", "given name"]),
        "last_name": (False, ["last", "last name", "surname", "family name"]),
        "phone": (False, ["phone", "mobile", "cell", "phone number", "contact"]),
        "age": (False, ["age"]),
        "birth_date": (False, ["dob", "birth date", "birthdate", "date of birth"]),
        "home_department": (True, ["department", "dept", "home dept", "home department", "area"]),
        "status": (False, ["status", "employment status", "emp type", "type", "ft/pt", "job status"]),
        "wage_per_hour": (True, ["wage", "wage rate", "pay rate", "rate", "hourly rate", "hourly wage", "pay"]),
        "hire_date": (False, ["hire date", "start date", "hired", "date hired"]),
        "min_hours_week": (False, ["min hours", "minimum hours", "min hrs"]),
        "max_hours_week": (False, ["max hours", "maximum hours", "max hrs"]),
        "trained_roles": (False, ["roles", "trained roles", "skills", "trained", "certifications", "training"]),
    },
    "training": {
        "employee_id": (True, ["id", "employee id", "emp id", "tm id", "tm_id", "team member id"]),
        "role": (True, ["role", "roles", "skill", "skills", "training", "trained role", "certification", "job"]),
    },
    "availability": {
        "employee_id": (True, ["id", "employee id", "emp id", "tm id", "tm_id", "team member id"]),
        **{f"avail_{d}": (False, [f"avail {d}", f"{d}", f"{d} avail", f"{d} availability", f"available {d}", full,
                                  *alts, *[f"avail {a}" for a in alts], *[f"{a} avail" for a in alts]])
           for d, full, alts in [("mon", "monday", ["mo"]), ("tue", "tuesday", ["tues", "tu"]),
                                 ("wed", "wednesday", ["weds", "we"]), ("thu", "thursday", ["thur", "thurs", "th"]),
                                 ("fri", "friday", ["fr"]), ("sat", "saturday", ["sa"]), ("sun", "sunday", ["su"])]},
        "note": (False, ["note", "notes", "comment", "comments"]),
    },
    "forecast": {
        "role": (True, ["role", "job", "position", "workload", "labor group"]),
        "day": (True, ["day", "date", "weekday", "dow", "day of week"]),
        "start": (True, ["start", "start time", "from", "time", "interval", "interval start", "begin"]),
        "end": (False, ["end", "end time", "to", "interval end", "finish"]),
        "duration": (False, ["duration", "length", "minutes", "mins", "interval length", "duration minutes"]),
        "headcount": (True, ["headcount", "hc", "staff", "required", "need", "needed", "required staff", "fte", "count"]),
    },
    "history": {
        "employee_id": (True, ["id", "employee id", "emp id", "tm id", "tm_id", "team member id"]),
        "date": (True, ["date", "shift date", "day", "work date"]),
        "start": (True, ["start", "start time", "in", "shift start", "from"]),
        "end": (True, ["end", "end time", "out", "shift end", "to"]),
        "role": (False, ["role", "job", "position"]),
    },
}

DAY_NAMES = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2, "thu": 3,
             "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6,
             "sunday": 6}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def parse_csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    columns = [c.strip() for c in (reader.fieldnames or []) if c is not None]
    rows = []
    for r in reader:
        rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items() if k is not None})
    return columns, rows


def heuristic_mapping(kind: str, columns: list[str]) -> dict[str, Optional[str]]:
    targets = TARGETS[kind]
    mapping: dict[str, Optional[str]] = {}
    used: set[str] = set()
    # exact synonym / field-name match first, then substring match
    for col in columns:
        n = norm(col)
        hit = next((f for f, (_, syn) in targets.items()
                    if f not in used and (n == norm(f) or n in [norm(s) for s in syn])), None)
        if hit:
            mapping[col] = hit
            used.add(hit)
    for col in columns:
        if col in mapping:
            continue
        n = norm(col)
        hit = next((f for f, (_, syn) in targets.items()
                    if f not in used and any(len(norm(s)) > 2 and re.search(rf"\b{re.escape(norm(s))}\b", n)
                                             for s in syn)), None)
        mapping[col] = hit
        if hit:
            used.add(hit)
    return mapping


def unmapped_required(kind: str, mapping: dict[str, Optional[str]]) -> list[str]:
    mapped = {v for v in mapping.values() if v}
    missing = [f for f, (req, _) in TARGETS[kind].items() if req and f not in mapped]
    if kind == "roster":
        if "name" in missing and {"first_name", "last_name"} <= mapped:
            missing.remove("name")
        if not ({"age", "birth_date"} & mapped):
            missing.append("age")
    if kind == "availability" and not any(v and v.startswith("avail_") for v in mapped):
        missing.append("avail_mon..avail_sun")
    return missing


async def llm_mapping(llm: LLMClient, kind: str, columns: list[str], sample: list[dict]) -> dict[str, Optional[str]]:
    fields = {f: ("required" if req else "optional") for f, (req, _) in TARGETS[kind].items()}
    prompt = (
        f"Map the columns of a retail '{kind}' CSV export to our fields.\n"
        f"Our fields: {json.dumps(fields)}\n"
        f"CSV columns: {json.dumps(columns)}\n"
        f"Sample rows: {json.dumps(sample[:5])}\n"
        "Reply with ONLY a JSON object {\"<csv column>\": \"<our field>\" or null}. Use each field at most once."
    )
    resp = await llm.complete([{"role": "user", "content": prompt}], [])
    text = (resp.content or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in mapping reply")
    raw = json.loads(m.group(0))
    valid = set(TARGETS[kind])
    out: dict[str, Optional[str]] = {c: None for c in columns}
    seen: set[str] = set()
    for col, field in raw.items():
        if col in out and field in valid and field not in seen:
            out[col] = field
            seen.add(field)
    return out


async def preview(kind: str, data: bytes, llm: Optional[LLMClient]) -> tuple[ImportPreview, list[dict]]:
    columns, rows = parse_csv(data)
    warnings: list[str] = []
    mapping = heuristic_mapping(kind, columns)
    if llm is not None and columns:
        try:
            proposed = await llm_mapping(llm, kind, columns, rows[:5])
            if len(unmapped_required(kind, proposed)) <= len(unmapped_required(kind, mapping)):
                mapping = proposed
        except Exception as e:  # noqa: BLE001
            warnings.append(f"LLM mapping unavailable ({type(e).__name__}); used name matching.")
    else:
        warnings.append("Column mapping proposed by name matching (no LLM configured). Please check it.")
    if not rows:
        warnings.append("The file has no data rows.")
    pv = ImportPreview(kind=kind, columns=columns, proposed_mapping=mapping,
                       unmapped_required=unmapped_required(kind, mapping),
                       rows_preview=rows[:20], row_count=len(rows), warnings=warnings,
                       target_fields=list(TARGETS[kind]),
                       required_fields=[f for f, (req, _) in TARGETS[kind].items() if req])
    return pv, rows


# --------------------------------------------------------------------------- #
# Deterministic value parsing
# --------------------------------------------------------------------------- #
def parse_time(s: str) -> int:
    s = s.strip().lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?", s)
    if not m:
        raise ValueError(f"bad time {s!r}")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        if h == 12:
            h = 0
        if ap.startswith("p"):
            h += 12
    return h * 60 + mi


def parse_window(s: str) -> tuple[int, int]:
    a, b = re.split(r"\s*(?:-|–|to)\s*", s.strip(), maxsplit=1)
    start, end = parse_time(a), parse_time(b)
    if end <= start:
        end += 1440
    return start, end


def parse_date(s: str) -> date:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    raise ValueError(f"bad date {s!r}")


def parse_money(s: str) -> float:
    return float(re.sub(r"[^0-9.\-]", "", s))


def phone_ok(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    return len(digits) == 10 or (len(digits) == 11 and digits.startswith("1"))


def parse_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits if digits else ""


def parse_status(s: str) -> str:
    n = norm(s)
    if n.startswith("f") or "full" in n:
        return "full_time"
    if "season" in n or n.startswith("seas") or n.startswith("temp"):
        return "seasonal"
    return "part_time"


def parse_day(s: str, week_start: date, warnings: list[str] | None = None, row: int | None = None) -> int:
    n = norm(s)
    if n in DAY_NAMES:
        return DAY_NAMES[n]
    if n.isdigit() and int(n) <= 6:
        return int(n)
    d = parse_date(s)
    day = (d - week_start).days % 7
    if warnings is not None and not week_start <= d < week_start + timedelta(days=7):
        warnings.append(f"Row {row}: date {d.isoformat()} is outside the schedule week starting "
                        f"{week_start.isoformat()}; used its weekday ({WEEKDAYS[day]}).")
    return day


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
OFF_WORDS = {"off", "na", "n a", "none", "unavailable", "unavail", "x", "no", "not available", "not avail",
             "closed", "-", "n", "no availability"}


def birth_date(s: str, on: date) -> tuple[date, bool]:
    """Parse a DOB. Two-digit years pivot to the century that gives an age of 14-90. Returns (date, pivoted)."""
    b = parse_date(s)
    if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2}", s.strip()):
        return b, False
    for year in (2000 + b.year % 100, 1900 + b.year % 100):
        cand = b.replace(year=year)
        if 14 <= age_on(cand, on) <= 90:
            return cand, cand.year != b.year
    return (b.replace(year=b.year - 100) if b > on else b), b > on


def age_on(b: date, on: date) -> int:
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def split_list(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;,|/]", s) if x.strip()]


# --------------------------------------------------------------------------- #
# Commit: apply mapped rows to the config dict (inside Database.mutate)
# --------------------------------------------------------------------------- #
class Resolver:
    """Resolves department / role names to ids, adding unknown ones as flagged defaults."""

    def __init__(self, d: dict, warnings: list[str]):
        self.d = d
        self.warnings = warnings

    def department(self, name: str) -> str:
        for dep in self.d["departments"]:
            if norm(name) in (norm(dep["id"]), norm(dep["name"])):
                return dep["id"]
        did = slug(name) or "unknown"
        self.d["departments"].append({"id": did, "name": name})
        self.warnings.append(f"Unknown department {name!r} added as {did!r} (default, review).")
        return did

    def role(self, name: str, department_id: Optional[str] = None) -> str:
        for r in self.d["roles"]:
            if norm(name) in (norm(r["id"]), norm(r["name"])):
                return r["id"]
        rid = slug(name) or "unknown"
        dep = department_id or (self.d["departments"][0]["id"] if self.d["departments"] else self.department("Unassigned"))
        self.d["roles"].append({"id": rid, "department_id": dep, "name": name, "gap_penalty_per_hour": 0.0,
                                "description": "Added from CSV import: unknown role name (default, provisional) — review."})
        self.warnings.append(f"Unknown role {name!r} added as {rid!r} with $0/h gap penalty (default, review).")
        return rid


def _mapped(row: dict, mapping: dict[str, Optional[str]]) -> dict[str, str]:
    return {field: row.get(col, "") for col, field in mapping.items() if field}


def apply_rows(kind: str, d: dict, mapping: dict[str, Optional[str]], rows: list[dict],
               warnings: list[str]) -> Any:
    res = Resolver(d, warnings)
    week_start = date.fromisoformat(d["store"]["week_start"])
    if kind == "roster":
        return _roster(d, mapping, rows, res, week_start, warnings)
    if kind == "training":
        by_id = {e["id"]: e for e in d["employees"]}
        for i, row in enumerate(rows):
            m = _mapped(row, mapping)
            e = by_id.get(m.get("employee_id", ""))
            if e is None:
                warnings.append(f"Row {i + 2}: unknown employee {m.get('employee_id')!r}; skipped.")
                continue
            for rname in split_list(m.get("role", "")):
                rid = res.role(rname, e["home_department_id"])
                if rid not in e["trained_role_ids"]:
                    e["trained_role_ids"].append(rid)
        return None
    if kind == "availability":
        by_id = {e["id"]: e for e in d["employees"]}
        for i, row in enumerate(rows):
            m = _mapped(row, mapping)
            e = by_id.get(m.get("employee_id", ""))
            if e is None:
                warnings.append(f"Row {i + 2}: unknown employee {m.get('employee_id')!r}; skipped.")
                continue
            entries = []
            for key, wd in [("avail_mon", 0), ("avail_tue", 1), ("avail_wed", 2), ("avail_thu", 3),
                            ("avail_fri", 4), ("avail_sat", 5), ("avail_sun", 6)]:
                if key not in m:
                    continue
                val = m[key].strip()
                if not val or norm(val) in ("any", "all", "all day", "open", "available"):
                    continue
                if norm(val) in OFF_WORDS or val.strip() == "-":
                    entries.append({"weekday": wd, "start": 0, "end": 1440, "kind": "unavailable",
                                    "source": "employee", "note": "CSV import"})
                    if norm(val).startswith("not"):
                        warnings.append(f"Row {i + 2}: {key}={val!r} read as unavailable all day.")
                    continue
                try:
                    windows = sorted(parse_window(w) for w in split_list(val.replace(",", ";")))
                except ValueError:
                    warnings.append(f"Row {i + 2}: could not read {key}={val!r}; left as available.")
                    continue
                t = 0
                for s, en in windows:  # unavailable = complement of the available windows within the day
                    if s > t:
                        entries.append({"weekday": wd, "start": t, "end": s, "kind": "unavailable",
                                        "source": "employee", "note": "CSV import"})
                    t = max(t, en)
                if t < 1440:
                    entries.append({"weekday": wd, "start": t, "end": 1440, "kind": "unavailable",
                                    "source": "employee", "note": "CSV import"})
            e["availability"] = [a for a in e.get("availability", []) if a.get("note") != "CSV import"] + entries
        return None
    if kind == "forecast":
        return _forecast(d, mapping, rows, res, week_start, warnings)
    if kind == "history":
        out = []
        for i, row in enumerate(rows):
            m = _mapped(row, mapping)
            try:
                out.append({"employee_id": m["employee_id"], "date": parse_date(m["date"]).isoformat(),
                            "start": parse_time(m["start"]), "end": parse_time(m["end"]), "role": m.get("role", "")})
            except (KeyError, ValueError) as e:
                warnings.append(f"Row {i + 2}: {e}; skipped.")
        return out
    raise ValueError(f"unknown import kind {kind!r}")


def _merge_slots(reqs: list[dict]) -> list[dict]:
    """Merge adjacent same-role/day/headcount slots into one requirement."""
    reqs = sorted(reqs, key=lambda r: (r["role_id"], r["day"], r["start"]))
    out: list[dict] = []
    for r in reqs:
        last = out[-1] if out else None
        if last and (last["role_id"], last["day"], last["headcount"]) == (r["role_id"], r["day"], r["headcount"]) \
                and last["end"] == r["start"]:
            last["end"] = r["end"]
        else:
            out.append(dict(r, id=f"fc_{len(out)}"))
    return out


def _roster(d, mapping, rows, res: Resolver, week_start: date, warnings: list[str]):
    by_id = {e["id"]: e for e in d["employees"]}
    seen_rows: dict[str, int] = {}
    for i, row in enumerate(rows):
        m = _mapped(row, mapping)
        try:
            eid = m["employee_id"].strip()
            if not eid:
                raise ValueError("empty employee id")
            name = m.get("name") or f"{m.get('first_name', '')} {m.get('last_name', '')}".strip()
            if m.get("age"):
                age = int(float(m["age"]))
            elif m.get("birth_date"):
                b, pivoted = birth_date(m["birth_date"], week_start)
                age = age_on(b, week_start)
                if pivoted:
                    warnings.append(f"Row {i + 2}: two-digit birth year {m['birth_date']!r} for {eid} read as "
                                    f"{b.isoformat()} (age {age}). Check it.")
            else:
                raise ValueError("no age or birth date")
            dep = res.department(m["home_department"])
            emp = dict(by_id.get(eid, {}))
            emp.update({
                "id": eid, "name": name, "age": age, "home_department_id": dep,
                "phone": parse_phone(m.get("phone", "")) or emp.get("phone") or "+10000000000",
                "status": parse_status(m["status"]) if m.get("status") else emp.get("status", "part_time"),
                "wage_per_hour": parse_money(m["wage_per_hour"]),
                "hire_date": parse_date(m["hire_date"]).isoformat() if m.get("hire_date") else emp.get("hire_date", week_start.isoformat()),
            })
            if not 14 <= age <= 90:
                warnings.append(f"Row {i + 2}: age {age} for {eid} looks wrong; please check it.")
            if m.get("phone") and not phone_ok(m["phone"]):
                warnings.append(f"Row {i + 2}: phone {m['phone']!r} for {eid} isn't a full 10-digit number; "
                                "kept as-is, outreach won't reach them.")
            if not m.get("phone"):
                warnings.append(f"Row {i + 2}: no phone for {eid}; placeholder +10000000000 set (outreach won't reach them).")
            if m.get("min_hours_week"):
                emp["min_hours_week"] = float(m["min_hours_week"])
            if m.get("max_hours_week"):
                emp["max_hours_week"] = float(m["max_hours_week"])
            trained = list(emp.get("trained_role_ids", []))
            for rname in split_list(m.get("trained_roles", "")):
                rid = res.role(rname, dep)
                if rid not in trained:
                    trained.append(rid)
            emp["trained_role_ids"] = trained
        except (KeyError, ValueError) as e:
            warnings.append(f"Row {i + 2}: {e}; skipped.")
            continue
        if eid in seen_rows:
            warnings.append(f"Row {i + 2}: duplicate employee id {eid} (also row {seen_rows[eid]}); this later row wins.")
        seen_rows[eid] = i + 2
        if eid in by_id:
            d["employees"] = [emp if x["id"] == eid else x for x in d["employees"]]
        else:
            d["employees"].append(emp)
        by_id[eid] = emp
    return None


def _forecast(d, mapping, rows, res: Resolver, week_start: date, warnings: list[str]):
    slot = d["store"]["slot_minutes"]
    parsed = []  # (row_no, role_id, day, start, end|None, headcount)
    for i, row in enumerate(rows):
        m = _mapped(row, mapping)
        try:
            day = parse_day(m["day"], week_start, warnings, i + 2)
            end = None
            if m.get("end"):
                start, end = parse_time(m["start"]), parse_time(m["end"])
                if end <= start:  # overnight, e.g. 10:00 PM -> 6:00 AM
                    end += 1440
            elif re.search(r"-|–| to ", m["start"]):
                start, end = parse_window(m["start"])
            else:
                start = parse_time(m["start"])
                if m.get("duration"):
                    end = start + int(float(m["duration"]))
            raw = float(m["headcount"] or 0)
        except (KeyError, ValueError) as e:
            warnings.append(f"Row {i + 2}: {e}; skipped.")
            continue
        hc = math.ceil(raw - 1e-9)
        if hc != raw and raw > 0:
            warnings.append(f"Row {i + 2}: headcount {m['headcount']} is not a whole number; rounded up to {hc}.")
        if hc <= 0:
            continue
        parsed.append((i + 2, res.role(m["role"]), day, start, end, hc))

    # start-only rows: each row lasts its group's own spacing (gap between consecutive starts)
    starts: dict[tuple[str, int], list[int]] = {}
    for _, rid, day, start, end, _ in parsed:
        if end is None:
            starts.setdefault((rid, day), []).append(start)

    def spacing(xs: list[int]) -> int | None:
        xs = sorted(set(xs))
        diffs = [b - a for a, b in zip(xs, xs[1:]) if b > a]
        return min(diffs) if diffs else None
    group_gap = {k: spacing(v) for k, v in starts.items()}
    file_gap = min((g for g in group_gap.values() if g), default=None)
    if starts and file_gap is None:
        warnings.append(f"Forecast rows have only a start time and no spacing to infer; each row assumed to last "
                        f"one {slot}-minute slot. Add an End or Duration column if that's wrong.")
    new = []
    for row_no, rid, day, start, end, hc in parsed:
        if end is None:
            end = start + (group_gap.get((rid, day)) or file_gap or slot)
        new.append({"id": f"fc_{row_no}", "role_id": rid, "day": day, "start": start, "end": end,
                    "headcount": hc, "source": "corporate"})

    # off-grid rows: roll up to the store's slots at the peak headcount (never fewer people than asked)
    roles = {r["id"]: r["name"] for r in d["roles"]}
    off = {(r["role_id"], r["day"]) for r in new if r["start"] % slot or r["end"] % slot}
    out = [r for r in new if (r["role_id"], r["day"]) not in off]
    for rid, day in sorted(off):
        peak: dict[int, int] = {}
        for r in new:
            if (r["role_id"], r["day"]) != (rid, day):
                continue
            t = r["start"] - r["start"] % slot
            while t < r["end"]:
                peak[t] = max(peak.get(t, 0), r["headcount"])
                t += slot
        out += [{"id": f"fc_{rid}_{day}_{t}", "role_id": rid, "day": day, "start": t, "end": t + slot, "headcount": h,
                 "source": "corporate"} for t, h in sorted(peak.items())]
        warnings.append(f"{roles.get(rid, rid)} {WEEKDAYS[day]}: times don't fit the store's {slot}-minute slots; "
                        f"rolled up to the peak headcount per {slot}-minute slot.")
    d["demand"] = [x for x in d["demand"] if x.get("source") != "corporate"] + _merge_slots(out)
    return None
