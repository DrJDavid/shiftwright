"""Generate the CSV import test packs (deterministic; synthetic people, phones 555-01xx only).

    uv run python packages/scenarios/import_packs/build.py

Writes clean_small_tx/, corporate_mid_tx/, messy_mid_ca/ and edge_cases/ next to this file,
plus a leader_setup.json per pack: the things a CSV cannot carry (store hours, payroll cap,
role priorities...) that the leader gives the chat. The CSVs are committed; re-running this
script must reproduce them byte-for-byte.
"""
from __future__ import annotations

import csv
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEEK_START = date(2026, 11, 9)  # Monday
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

FIRST = ["Avery", "Blake", "Cam", "Dana", "Eli", "Frankie", "Gale", "Harper", "Indy", "Jules", "Kai", "Lane",
         "Morgan", "Noor", "Oakley", "Parker", "Quinn", "Rowan", "Sage", "Tatum", "Uri", "Vale", "Wren", "Xen",
         "Yael", "Zion", "Arden", "Bryn", "Cove", "Dell", "Ember", "Finch", "Greer", "Haven", "Ira", "Jory",
         "Kit", "Lux", "Marlo", "Nico", "Ozzie", "Pax", "Remi", "Shay", "Tobin", "Umber", "Vesper", "Wynn"]
LAST = ["Abara", "Bellweather", "Castellan", "Dunmore", "Eskew", "Fairlow", "Grayling", "Hollister", "Ivanko",
        "Jessup", "Kettering", "Lowell", "Marchetti", "Northcott", "Okafor", "Pemberly", "Quarles", "Ravensworth",
        "Stroud", "Thistle", "Underhill", "Vantassel", "Whitlock", "Yarrow", "Zeller", "Ashgrove", "Brightwater",
        "Coldiron", "Drummond", "Elsworth"]


def names(rng: random.Random, n: int) -> list[str]:
    pool = [f"{f} {l}" for f in FIRST for l in LAST]
    rng.shuffle(pool)
    return pool[:n]


def t12(m: int) -> str:
    h, mi = divmod(m % 1440, 60)
    ap = "AM" if h < 12 else "PM"
    return f"{(h % 12) or 12}:{mi:02d} {ap}"


def t24(m: int) -> str:
    h, mi = divmod(m % 1440, 60)
    return f"{h:02d}:{mi:02d}"


def write_csv(path: Path, header: list[str], rows: list[list], *, preamble: str = "", bom: bool = False,
              encoding: str = "utf-8") -> None:
    buf = io.StringIO()
    buf.write(preamble)
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    data = buf.getvalue().encode(encoding)
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n")


def dob_for_age(rng: random.Random, age: int) -> date:
    # born `age` years before week start, minus 30..300 days, so the age is exact on WEEK_START
    return date(WEEK_START.year - age, WEEK_START.month, WEEK_START.day) - timedelta(days=rng.randint(30, 300))


def history_rows(rng, emps, demand_roles, weeks=2, fmt=t12, date_fmt="%Y-%m-%d"):
    """Plausible past shifts: each employee works 3-5 days a week in one of their trained roles."""
    out = []
    first = WEEK_START - timedelta(days=7 * weeks)
    for w in range(weeks):
        for e in emps:
            roles = [r for r in e["roles"] if r in demand_roles]
            if not roles:
                continue
            for d in sorted(rng.sample(range(7), rng.randint(3, 5))):
                start = rng.choice([7, 8, 9, 10, 12, 14]) * 60
                length = rng.choice([4, 5, 6, 8]) * 60
                end = min(start + length, 22 * 60)
                day = first + timedelta(days=7 * w + d)
                out.append([e["id"], day.strftime(date_fmt), fmt(start), fmt(end), rng.choice(roles)])
    return out


# --------------------------------------------------------------------------- #
# 1. clean_small_tx
# --------------------------------------------------------------------------- #
def clean_small_tx() -> None:
    rng = random.Random(101)
    d = HERE / "clean_small_tx"
    nm = names(rng, 15)
    # (dept, status, wage, age, roles, availability per day or None)
    STUDENT = ["3:00 PM-9:00 PM"] * 5 + ["ALL", "ALL"]
    spec = [
        ("Leadership", "FT", 24.50, 38, ["Leader on Duty", "Guest Service Desk", "Cashier"], None),
        ("Leadership", "FT", 23.00, 31, ["Leader on Duty", "Guest Service Desk", "Cashier"], None),
        ("Leadership", "FT", 22.75, 44, ["Leader on Duty", "Guest Service Desk", "Drive Up"], None),
        ("Front of Store", "FT", 16.50, 27, ["Cashier", "Guest Service Desk"], None),
        ("Front of Store", "PT", 15.25, 19, ["Cashier", "Drive Up"], STUDENT),
        ("Front of Store", "PT", 15.00, 17, ["Cashier"], STUDENT),
        ("Front of Store", "PT", 15.75, 52, ["Cashier", "Guest Service Desk"], ["ALL", "ALL", "OFF", "ALL", "ALL", "ALL", "OFF"]),
        ("Front of Store", "FT", 17.25, 35, ["Cashier", "Drive Up", "Guest Service Desk"], None),
        ("Front of Store", "PT", 15.50, 23, ["Drive Up", "Cashier"], ["9:00 AM-3:00 PM"] * 5 + ["OFF", "ALL"]),
        ("Front of Store", "PT", 15.25, 20, ["Drive Up", "Cashier"], None),
        ("General Merchandise", "FT", 16.75, 41, ["Softlines", "Cashier"], None),
        ("General Merchandise", "PT", 15.50, 29, ["Softlines", "Drive Up"], ["OFF", "ALL", "ALL", "ALL", "ALL", "ALL", "ALL"]),
        ("General Merchandise", "PT", 15.25, 18, ["Softlines", "Cashier"], STUDENT),
        ("General Merchandise", "PT", 16.00, 60, ["Softlines", "Guest Service Desk"], ["9:00 AM-5:00 PM"] * 7),
        ("General Merchandise", "PT", 15.00, 24, ["Cashier", "Softlines", "Drive Up"], None),
    ]
    emps = []
    roster, training, avail = [], [], []
    for i, (dept, st, wage, age, roles, av) in enumerate(spec):
        eid = f"1{i + 1:03d}"
        emps.append({"id": eid, "roles": roles})
        hire = WEEK_START - timedelta(days=rng.randint(60, 2500))
        mn, mx = (32, 40) if st == "FT" else (12, 29)
        roster.append([eid, nm[i], dept, st, f"{wage:.2f}", dob_for_age(rng, age).isoformat(), hire.isoformat(),
                       f"512-555-01{i:02d}", mn, mx])
        training += [[eid, r] for r in roles]
        avail.append([eid] + (av or ["ALL"] * 7) + ["student" if av is STUDENT else ""])
    write_csv(d / "roster.csv", ["Employee ID", "Name", "Department", "Status", "Wage", "Birth Date", "Hire Date",
                                 "Phone", "Min Hours", "Max Hours"], roster)
    write_csv(d / "training.csv", ["Employee ID", "Role"], training)
    write_csv(d / "availability.csv", ["Employee ID"] + [f"Avail {x}" for x in DAYS] + ["Notes"], avail)

    # windowed forecast, store open 9:00-21:00 every day
    blocks = [("Leader on Duty", 540, 1260, 1), ("Guest Service Desk", 540, 1260, 1), ("Cashier", 540, 660, 1),
              ("Cashier", 660, 1140, 2), ("Cashier", 1140, 1260, 1), ("Drive Up", 600, 1080, 1),
              ("Softlines", 540, 780, 1)]
    fc = [[role, DAYS[day], t12(s), t12(e), hc] for day in range(7) for role, s, e, hc in blocks]
    write_csv(d / "forecast.csv", ["Role", "Day", "Start", "End", "Headcount"], fc)
    hist = history_rows(rng, emps, {b[0] for b in blocks}, weeks=2)
    write_csv(d / "history.csv", ["Employee ID", "Date", "Start", "End", "Role"], hist)
    write_json(d / "leader_setup.json", {
        "_what": "What the leader tells the chat (store_basics + payroll cards, role priorities). Not in any CSV.",
        "template": "empty", "name": "Store #2104 Round Rock (clean test)", "jurisdiction": {"state": "TX", "city": None},
        "timezone": "America/Chicago", "slot_minutes": 30,
        "hours": {"open": "09:00", "close": "21:00", "days": "every day"},
        "pre_open_minutes": 60, "post_close_minutes": 60,
        "weekly_hours_cap": 420,
        "gap_penalty_per_hour": {"leader_on_duty": 200, "guest_service_desk": 40, "cashier": 30,
                                 "drive_up": 25, "softlines": 20},
    })


# --------------------------------------------------------------------------- #
# 2. corporate_mid_tx
# --------------------------------------------------------------------------- #
CORP_ROLES = ["Leader on Duty", "Cashier", "Guest Service", "Softlines", "Hardlines", "Drive Up", "Order Pick",
              "Truck Unload"]


def corporate_mid_tx() -> None:
    rng = random.Random(202)
    d = HERE / "corporate_mid_tx"
    nm = names(rng, 40)
    EARLY = ["04:00-13:00"] * 7
    # (home org, emp type, count, base wage, role options, availability pattern)
    groups = [
        ("LEADERSHIP", "Full-Time", 6, 24.0, [["Leader on Duty", "Guest Service", "Cashier"],
                                               ["Leader on Duty", "Truck Unload", "Hardlines"]]),
        ("FRONT END", "Part-Time", 8, 15.0, [["Cashier", "Guest Service"], ["Cashier", "Drive Up"], ["Cashier"]]),
        ("GUEST SERVICE", "Part-Time", 4, 15.75, [["Guest Service", "Cashier"]]),
        ("SOFTLINES", "Part-Time", 6, 15.25, [["Softlines", "Cashier"], ["Softlines"]]),
        ("HARDLINES", "Part-Time", 5, 15.25, [["Hardlines", "Truck Unload"], ["Hardlines", "Cashier"]]),
        ("FULFILLMENT", "Part-Time", 6, 15.5, [["Order Pick", "Drive Up"], ["Order Pick", "Drive Up", "Cashier"]]),
        ("FLOW", "Part-Time", 5, 16.0, [["Truck Unload", "Hardlines"], ["Truck Unload", "Softlines"]]),
    ]
    roster, training, avail, emps = [], [], [], []
    i = 0
    for org, etype, n, base, role_opts in groups:
        for k in range(n):
            eid = f"00{48100 + i}"  # Workday-style zero-padded ids (strings)
            roles = role_opts[k % len(role_opts)]
            st = etype if not (org != "LEADERSHIP" and k == 0) else "Full-Time"
            if org == "SOFTLINES" and k == n - 1:
                st = "Seasonal"
            ft = st == "Full-Time"
            age = rng.randint(19, 62)
            wage = base + rng.choice([0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0])
            hire = WEEK_START - timedelta(days=rng.randint(20, 4000))
            roster.append([eid, nm[i], org, f"{org.title()} {'Lead' if ft and org != 'LEADERSHIP' else 'TM'}",
                           st, f"${wage:,.2f}", 40 if ft else 24, 32 if ft else 0, 40 if ft else 30,
                           dob_for_age(rng, age).strftime("%m/%d/%Y"), hire.isoformat(),
                           f"(281) 555-01{20 + i:02d}", "Store T2290"])
            training += [[eid, r, (hire + timedelta(days=rng.randint(7, 90))).strftime("%m/%d/%Y")] for r in roles]
            if org == "FLOW" or "Truck Unload" in roles and org == "LEADERSHIP":
                av = EARLY
            elif k % 4 == 1:
                av = ["16:00-22:00"] * 5 + ["ANY", "ANY"]
            elif k % 4 == 2:
                off = rng.sample(range(7), 2)
                av = ["OFF" if x in off else "ANY" for x in range(7)]
            else:
                av = ["ANY"] * 7
            avail.append([eid, nm[i]] + av + ["2026-10-01"])
            emps.append({"id": eid, "roles": roles})
            i += 1
    write_csv(d / "roster.csv", ["Employee ID", "Legal Name", "Home Org", "Job Profile", "Emp Type", "Pay Rate",
                                 "Std Hrs", "Min Hrs/Wk", "Max Hrs/Wk", "Date of Birth", "Hire Date",
                                 "Mobile Phone", "Location"], roster)
    write_csv(d / "training.csv", ["Employee ID", "Skill Name", "Completed On"], training)
    write_csv(d / "availability.csv", ["Employee ID", "Legal Name"] + FULL_DAYS + ["Last Updated"], avail)

    # per-30-minute interval forecast, store 08:00-22:00, truck Tue/Thu/Sat 04:00-10:00
    def need(role: str, day: int, t: int) -> int:
        if role == "Leader on Duty":
            return 1 if 480 <= t < 1320 else 0
        if role == "Cashier":
            return 1 if 480 <= t < 600 or 1200 <= t < 1320 else 2 if 600 <= t < 1020 else 3 if t < 1200 and t >= 1020 else 0
        if role == "Guest Service":
            return 1 if 480 <= t < 1320 else 0
        if role in ("Softlines", "Hardlines"):
            return 2 if 540 <= t < 780 else 1 if 780 <= t < 1080 else 0
        if role == "Drive Up":
            return 1 if 540 <= t < 1260 else 0
        if role == "Order Pick":
            return 2 if 420 <= t < 780 else 1 if 780 <= t < 1020 else 0
        if role == "Truck Unload":
            return 4 if day in (1, 3, 5) and 240 <= t < 600 else 0
        raise KeyError(role)
    fc = []
    for day in range(7):
        dt = (WEEK_START + timedelta(days=day)).isoformat()
        for role in CORP_ROLES:
            for t in range(240, 1320, 30):
                hc = need(role, day, t)
                if hc:
                    fc.append([dt, f"T2290 > {role.upper()}", role, t24(t), t24(t + 30), f"{hc:.1f}"])
    write_csv(d / "forecast.csv", ["Business Date", "Org Path", "Job", "Interval Start", "Interval End", "Req FTE"], fc)
    hist = history_rows(rng, emps, set(CORP_ROLES), weeks=4, fmt=t12, date_fmt="%m/%d/%Y")
    hist = [[r[0], r[1], r[4], r[2], r[3]] for r in hist]
    write_csv(d / "history.csv", ["Employee ID", "Work Date", "Job", "Punch In", "Punch Out"], hist)
    write_json(d / "leader_setup.json", {
        "_what": "What the leader tells the chat. Not in any CSV.",
        "template": "empty", "name": "Store T2290 Katy (corporate test)", "jurisdiction": {"state": "TX", "city": None},
        "timezone": "America/Chicago", "slot_minutes": 30,
        "hours": {"open": "08:00", "close": "22:00", "days": "every day"},
        "pre_open_minutes": 240, "post_close_minutes": 60,
        "truck_days": {"days": ["Tue", "Thu", "Sat"], "start": "04:00", "end": "10:00"},
        "weekly_hours_cap": 900,
        "manual_mappings": {"roster": {"Home Org": "home_department"},
                            "history": {"Punch In": "start", "Punch Out": "end"}},
        "gap_penalty_per_hour": {"leader_on_duty": 200, "cashier": 30, "guest_service": 40, "softlines": 20,
                                 "hardlines": 20, "drive_up": 25, "order_pick": 25, "truck_unload": 35},
    })


# --------------------------------------------------------------------------- #
# 3. messy_mid_ca
# --------------------------------------------------------------------------- #
def messy_mid_ca() -> None:
    rng = random.Random(303)
    d = HERE / "messy_mid_ca"
    nm = names(rng, 26)
    FE = ["Front End", "FRONT END", "front end", "Front-End"]
    DOBF = ["%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y", "%m/%d/%y"]
    WAGEF = ["${:.2f}", "{:.2f}", "{:.2f}/hr", " $ {:.2f} ", "{:g}"]
    STAT = ["PT", "Part Time", "P/T", "part-time"]
    # id, dept, status, wage, age, skills (training rows), availability Mon..Sun
    A = ["ANY"] * 7
    base = [
        (2201, "Leadership", "FT", 24.00, 41, ["LOD", "GSA; CASHIER"], A),
        (2202, "LEADERSHIP", "FT", 25.50, 35, ["LOD", "GSA"], A),
        (2203, "leadership", "FT", 23.75, 29, ["LOD", "CASHIER", "TRUCK"], ["OFF", "ANY", "ANY", "ANY", "ANY", "ANY", "OFF"]),
        (2204, "Leadership", "FT", 26.00, 47, ["LOD", "FORKLIFT", "TRUCK"], ["ANY", "ANY", "ANY", "ANY", "ANY", "N/A", "ANY"]),
        (2205, None, None, 17.25, 22, ["CASHIER", "GSA"], ["9a-5p"] * 5 + ["", ""]),
        (2206, None, None, 17.00, 19, ["CASHIER", "DRIVE UP"], ["4pm-10pm"] * 5 + ["ANY", "ANY"]),
        (2207, None, None, 17.00, 33, ["CASHIER"], A),
        (2208, None, None, 17.50, 58, ["CASHIER", "GSA"], ["8:00 AM - 12:00 PM, 5:00 PM - 9:00 PM"] * 7),
        (2209, None, None, 17.10, 24, ["DRIVE UP", "CASHIER"], ["OFF", "OFF", "ANY", "ANY", "ANY", "ANY", "ANY"]),
        (2210, None, None, 17.30, 27, ["DRIVE UP", "GSA"], A),
        (2211, "Softlines", "PT", 17.00, 36, ["SOFTLINES", "CASHIER"], A),
        (2212, "Softlines", "PT", 15.50, 21, ["SOFTLINES"], A),            # PLANT: below CA minimum
        (2213, "SOFTLINES", "Seas", 17.00, 20, ["SOFTLINES", "ZZ-TEMP"], ["Not Available", "ANY", "ANY", "ANY", "ANY", "ANY", "ANY"]),
        (2214, "Softlines", "PT", 17.40, 45, ["SOFTLINES", "CASHIER"], ["after 4pm"] * 5 + ["ANY", "ANY"]),
        (2215, "Hardlines", "FT", 18.00, 39, ["HARDLINES", "TRUCK"], A),
        (2216, "Hardlines", "PT", 17.20, 26, ["HARDLINES"], A),
        (2217, "HARDLINES", "PT", 17.60, 31, ["HARDLINES", "CASHIER"], A),
        (2218, "Flow", "FT", 18.50, 34, ["TRUCK", "FORKLIFT"], ["04:00-12:30"] * 4 + ["OFF", "OFF", "ANY"]),
        (2219, "Flow", "PT", 17.00, 16, ["TRUCK", "FORKLIFT"], A),         # PLANT: 16-year-old on forklift
        (2220, "Flow", "PT", 18.25, 28, ["TRUCK", "FORKLIFT"], ["ANY"] * 5 + ["OFF", "ANY"]),
        (2221, "FLOW", "PT", 17.80, 23, ["TRUCK", "HARDLINES"], A),
        (2222, "Flow", "PT", 17.00, 30, ["TRUCK", "SOFTLINES"], A),
        (2223, None, None, 17.00, 64, ["CASHIER", "GSA"], A),               # PLANT: DOB 2-digit year '62
        (2224, None, None, 17.25, 27, ["CASHIER"], A),                      # PLANT: unparseable DOB
        (2225, None, None, 17.00, 25, ["CASHIER", "DRIVE UP"], A),          # PLANT: phone w/o area code
    ]
    header = ["Store #", "Emp ID", "Employee Name", "Dept", "Manager", "Type", "Rate", "DOB", "Hire Dt", "Mobile",
              "Email", ""]
    roster = []
    for i, (eid, dept, st, wage, age, _, _) in enumerate(base):
        dept = dept or FE[i % 4]
        st = st or STAT[i % 4]
        dob = dob_for_age(rng, age)
        dob_s = dob.strftime(DOBF[i % 4]) if age < 60 or i % 4 != 3 else dob.strftime("%m/%d/%Y")
        if eid == 2223:
            dob_s = date(1962, 7, 4).strftime("%-m/%-d/%y")
        if eid == 2224:
            dob_s = "March 3, 1999"
        if eid == 2219:
            dob_s = dob.strftime("%Y-%m-%d")
        phone = f"(916) 555-01{60 + i:02d}" if i % 2 else f"916.555.01{60 + i:02d}"
        if eid == 2225:
            phone = "555-0185"
        mgr = nm[0] if dept.lower().startswith("lead") else nm[1 + i % 3]
        hire = (WEEK_START - timedelta(days=rng.randint(30, 3000))).strftime("%m/%d/%Y")
        roster.append(["2291", str(eid), nm[i], dept, mgr, st, WAGEF[i % 5].format(wage), dob_s, hire, phone,
                       f"tm{eid}@example.invalid", ""])
        if eid == 2208:
            roster.append([""] * 12)  # PLANT: blank row of commas
        if eid == 2216:
            roster.append([""] * 12)  # second blank row
    # PLANT: duplicate row for 2207 (raise processed, old row not removed); last one wins
    roster.append(["2291", "2207", nm[6], "Front End", nm[2], "PT", "$18.25", roster[6][7], roster[6][8], roster[6][9],
                   "tm2207@example.invalid", ""])
    write_csv(d / "roster.csv", header, roster)

    training = []
    for eid, *_rest in base:
        skills = _rest[4]
        sid = f"{eid}.0" if eid == 2215 else str(eid)   # PLANT: Excel turned 2215 into 2215.0
        for s in skills:
            training.append([sid, s, (WEEK_START - timedelta(days=rng.randint(10, 700))).strftime("%m/%d/%Y"), ""])
    training.append(["9999", "CASHIER", "01/05/2026", ""])  # PLANT: unknown employee
    write_csv(d / "training.csv", ["Emp ID", "Skill", "Cert Date", "Expires"], training)

    avail = [[str(eid), nm[i]] + av + ([""]) for i, (eid, *_, av) in enumerate(base)]
    avail.insert(10, ["", "", "", "", "", "", "", "", "", ""])
    avail.append(["8888", "Former TM", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF", "OFF", "termed"])
    write_csv(d / "availability.csv", ["Emp ID", "Employee Name", "Mon", "Tue", "Weds", "Thurs", "Fri", "Sat", "Sun",
                                       "Comments"], avail)

    # hourly per-slot forecast with only a "Time" column; store 08:00-22:00, 30-min slots
    day_label = ["Mon", "Tuesday", "2026-11-11", "Thurs", "11/13/2026", "Sat", "Sunday"]
    fc = []
    for day in range(7):
        for h in range(4, 22):
            t = h * 60
            rows = []
            if 8 <= h < 22:
                rows += [("Leadership", "LOD", 1), ("Front End", "GSA", 1),
                         ("Front End", "CASHIER", 2 if 10 <= h < 19 else 1)]
            if 9 <= h < 20:
                rows.append(("Front End", "DRIVE UP", "1.5" if 16 <= h < 18 else 1))
            if 9 <= h < 15:
                rows += [("Softlines", "SOFTLINES", 1), ("Hardlines", "HARDLINES", 1)]
            if day in (2, 5) and 5 <= h < 10:
                rows.append(("Flow", "TRUCK", 3))
            if day in (2, 5) and 6 <= h < 9:
                rows.append(("Flow", "FORKLIFT", 1 if day == 2 else 2))
            if day in (5, 6) and 10 <= h < 14:
                rows.append(("Front End", "BEAUTY", 1))   # PLANT: nobody trained
            if day == 0 and 15 <= h < 17:
                rows.append(("Front End", "CASHIER", "0.5"))  # PLANT: fractional duplicate need, dropped
            fc += [[dept, job, day_label[day], t12(t) if day % 2 else t24(t), hc, ""] for dept, job, hc in rows]
    write_csv(d / "forecast.csv", ["Dept", "Job Code", "Day", "Time", "HC", "Notes"], fc)

    emps = [{"id": str(b[0]), "roles": [r.strip() for s in b[5] for r in s.split(";")]} for b in base]
    hist = history_rows(rng, emps, {"LOD", "GSA", "CASHIER", "DRIVE UP", "SOFTLINES", "HARDLINES", "TRUCK"}, weeks=2,
                        fmt=t12, date_fmt="%m/%d/%Y")
    pre = ("Kronos Workforce Central - Punch Detail Report\n"
           "Store 2291 Sacramento CA | Run 11/06/2026 04:12 | Page 1 of 1\n\n")
    write_csv(d / "history.csv", ["Emp ID", "Date", "In", "Out", "Job"], hist, preamble=pre)
    write_json(d / "leader_setup.json", {
        "_what": "What the leader tells the chat. Not in any CSV.",
        "template": "empty", "name": "Store 2291 Sacramento (messy test)", "jurisdiction": {"state": "CA", "city": None},
        "timezone": "America/Los_Angeles", "slot_minutes": 30,
        "hours": {"open": "08:00", "close": "22:00", "days": "every day"},
        "pre_open_minutes": 180, "post_close_minutes": 60,
        "weekly_hours_cap": 700,
        "manual_mappings": {"roster": {"Manager": None}},
        "gap_penalty_per_hour": {"lod": 200, "gsa": 40, "cashier": 30, "drive_up": 25, "softlines": 20,
                                 "hardlines": 20, "truck": 35, "forklift": 35, "beauty": 15, "zz_temp": 0},
        "fixes_after_review": {
            "wage": {"2212": 17.00},
            "age": {"2223": 64},
            "phone": {"2225": "+19165550185"},
            "train": {"2211": ["beauty"], "2213": ["beauty"], "2215": ["hardlines", "truck"]},
            "role_tags": {"forklift": ["powered_industrial_truck"]},
            "role_min_age": {"forklift": 18},
            "gap_penalty": {"beauty": 25},
        },
    })


# --------------------------------------------------------------------------- #
# 4. edge_cases
# --------------------------------------------------------------------------- #
def edge_cases() -> None:
    d = HERE / "edge_cases"
    write_csv(d / "roster_base.csv", ["Employee ID", "Name", "Department", "Wage", "Age", "Phone"], [
        ["E1", "Avery Quarles", "Front of Store", "15.00", 30, "512-555-0190"],
        ["E2", "Blake Stroud", "Front of Store", "15.00", 25, "512-555-0191"],
    ])
    write_csv(d / "roster_bom.csv", ["Employee ID", "Name", "Department", "Wage", "Age", "Phone"],
              [["E3", "Cam Thistle", "Front of Store", "15.50", 22, "512-555-0192"]], bom=True)
    write_csv(d / "roster_first_last_age.csv", ["TM ID", "First Name", "Last Name", "Dept", "Hourly Rate", "Age",
                                                "Cell"],
              [["E4", "Dana", "Underhill", "Front of Store", "$16.00", 45, "+1 512 555 0193"]])
    write_csv(d / "roster_missing_wage.csv", ["Employee ID", "Name", "Department", "DOB"],
              [["E5", "Eli Whitlock", "Front of Store", "1990-01-01"]])
    write_csv(d / "roster_header_only.csv", ["Employee ID", "Name", "Department", "Wage", "Age"], [])
    write_csv(d / "roster_utf8_names.csv", ["Employee ID", "Name", "Department", "Wage", "Age", "Phone"],
              [["E6", "José Núñez-Ortíz", "Front of Store", "15.00", 33, "512-555-0194"]])
    write_csv(d / "training_list_in_cell.csv", ["Employee ID", "Skills"],
              [["E1", "Cashier|Drive Up/Guest Service Desk"], ["E2", "Cashier, Drive Up"]])
    write_csv(d / "availability_overnight.csv", ["Employee ID", "Avail Mon", "Avail Tue"],
              [["E1", "22:00-06:00", "OFF"], ["E2", "6pm-12am", "N/A"]])
    write_csv(d / "forecast_overnight_window.csv", ["Role", "Day", "Interval", "Headcount"],
              [["Cashier", "Fri", "22:00-06:00", 1]])
    write_csv(d / "forecast_overnight_end_column.csv", ["Role", "Day", "Start", "End", "Headcount"],
              [["Cashier", "Fri", "10:00 PM", "6:00 AM", 1]])
    write_csv(d / "forecast_15min_slots.csv", ["Role", "Day", "Interval Start", "Headcount"],
              [["Cashier", "Mon", t24(600 + 15 * k), hc] for k, hc in enumerate([2, 3, 3, 2, 2, 3, 3, 2])])
    write_csv(d / "forecast_hourly_start_only.csv", ["Role", "Day", "Time", "Headcount"],
              [["Cashier", "Tue", t24(t), 1] for t in range(600, 780, 60)])
    write_csv(d / "forecast_other_week_dates.csv", ["Role", "Date", "Start", "End", "Headcount"],
              [["Cashier", "2026-11-18", "10:00", "12:00", 1]])
    write_csv(d / "forecast_fractional_hc.csv", ["Role", "Day", "Start", "End", "Headcount"],
              [["Cashier", "Thu", "10:00", "12:00", "0.5"], ["Cashier", "Thu", "12:00", "14:00", "1.6"]])
    write_csv(d / "history_basic.csv", ["Employee ID", "Shift Date", "Shift Start", "Shift End", "Role"],
              [["E1", "11/02/2026", "8:00 AM", "4:30 PM", "Cashier"], ["E2", "02-Nov-2026", "13:00", "21:00", "Cashier"]])


if __name__ == "__main__":
    clean_small_tx()
    corporate_mid_tx()
    messy_mid_ca()
    edge_cases()
    print("wrote packs under", HERE)
