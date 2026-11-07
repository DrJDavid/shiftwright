"""Generate the corporate-style DEMAND import packs (deterministic, synthetic).

    uv run python packages/scenarios/import_packs/demand/build_demand.py

Every file is derived from one synthetic "truth" per week variant (hourly transactions, online
orders, truck cases) plus one set of labor standards, using spec_reference.py. So the five styles
describe the same store-week and can be compared or mixed. Roles and departments are
corporate_mid_tx's (Store T2290 Katy TX), so these files import on top of that pack's roster.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import spec_reference as ref  # noqa: E402

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SLOT = 30

# role name -> department (corporate_mid_tx Home Org values)
ROLE_DEPT = {"Leader on Duty": "LEADERSHIP", "Cashier": "FRONT END", "Guest Service": "GUEST SERVICE",
             "Softlines": "SOFTLINES", "Hardlines": "HARDLINES", "Drive Up": "FULFILLMENT",
             "Order Pick": "FULFILLMENT", "Truck Unload": "FLOW"}
DEPTS = ["LEADERSHIP", "FRONT END", "GUEST SERVICE", "SOFTLINES", "HARDLINES", "FULFILLMENT", "FLOW"]

# Labor standards (synthetic corporate labor model; NOT law)
STANDARDS = [
    {"role": "Leader on Duty", "driver": "fixed", "per": None, "min": 1, "max": 1},
    {"role": "Cashier", "driver": "transactions", "per": 40, "min": 1, "max": 8},
    {"role": "Guest Service", "driver": "transactions", "per": 160, "min": 1, "max": 3},
    {"role": "Drive Up", "driver": "online_orders", "per": 12, "min": 1, "max": 4},
    {"role": "Order Pick", "driver": "online_orders", "per": 12, "min": 0, "max": 4},
]
UNLOAD = {"role": "Truck Unload", "driver": "cases", "per": 180, "min": 3, "max": 6, "max_hours": 4}
TRUCK_ARRIVAL = 4 * 60

# hourly base curves (hour -> value) for a normal Monday
BASE_TXN = {6: 30, 7: 35, 8: 40, 9: 55, 10: 70, 11: 85, 12: 95, 13: 90, 14: 85, 15: 90, 16: 105, 17: 115,
            18: 100, 19: 75, 20: 50, 21: 30, 22: 20}
BASE_ONLINE = {6: 4, 7: 6, 8: 8, 9: 12, 10: 14, 11: 13, 12: 12, 13: 11, 14: 10, 15: 10, 16: 11, 17: 12,
               18: 10, 19: 8, 20: 5, 21: 3, 22: 2}
QUARTER_SHAPE = [Fraction(22, 100), Fraction(25, 100), Fraction(28, 100), Fraction(25, 100)]
AVG_TICKET = Fraction(4850, 100)

ALL_8_22 = {d: ("08:00", "22:00") for d in DAYS}
VARIANTS = {
    "normal": {
        "week_start": date(2026, 11, 9), "label": "Normal November week",
        "hours": ALL_8_22,
        "txn_mult": [1.0, 0.95, 1.0, 1.05, 1.15, 1.35, 1.15], "online_mult": [1.0, 1.0, 1.0, 1.05, 1.1, 1.3, 1.2],
        "trucks": {"Tue": 2880, "Thu": 2880, "Sat": 3240},
    },
    "holiday": {
        "week_start": date(2026, 11, 23), "label": "Thanksgiving week (closed Thu, Black Friday 6am-11pm)",
        "hours": {"Mon": ("08:00", "22:00"), "Tue": ("08:00", "22:00"), "Wed": ("08:00", "22:00"),
                  "Fri": ("06:00", "23:00"), "Sat": ("07:00", "23:00"), "Sun": ("08:00", "22:00")},
        "txn_mult": [1.2, 1.25, 1.5, 0, 2.4, 1.9, 1.4], "online_mult": [1.3, 1.4, 1.6, 0, 2.2, 1.8, 1.5],
        "doorbuster": {"Fri": {6: 1.6, 7: 1.6, 8: 1.4, 9: 1.2}},
        "trucks": {"Mon": 3600, "Tue": 3600, "Wed": 4320, "Sat": 3240},
    },
    "promo": {
        "week_start": date(2026, 11, 16), "label": "Promo week (weekend deals Fri-Sun, online push)",
        "hours": ALL_8_22,
        "txn_mult": [1.0, 0.95, 1.0, 1.05, 1.3, 1.75, 1.5], "online_mult": [1.0, 1.0, 1.0, 1.1, 1.7, 1.9, 1.8],
        "trucks": {"Tue": 2880, "Thu": 3600, "Sat": 2880},
    },
    "light_january": {
        "week_start": date(2027, 1, 11), "label": "Light January week (Sun 10am-8pm)",
        "hours": {**{d: ("08:00", "22:00") for d in DAYS[:6]}, "Sun": ("10:00", "20:00")},
        "txn_mult": [0.7, 0.65, 0.7, 0.7, 0.8, 0.95, 0.8], "online_mult": [0.8, 0.8, 0.8, 0.8, 0.85, 0.95, 0.9],
        "trucks": {"Wed": 2160, "Sat": 2160},
    },
}

# fixed staffing plan for the non-sales roles (windowed_roles), same in every week
PLAN = [("SOFTLINES", "Softlines", "Mon-Sun", "09:00", "13:00", 2),
        ("SOFTLINES", "Softlines", "Mon-Sun", "13:00", "18:00", 1),
        ("HARDLINES", "Hardlines", "Mon-Sun", "09:00", "13:00", 2),
        ("HARDLINES", "Hardlines", "Mon-Sun", "13:00", "18:00", 1)]


def tmin(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def t24(m: int) -> str:
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def t12(m: int) -> str:
    h, mi = divmod(m % 1440, 60)
    return f"{(h % 12) or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"


def open_hours(v: dict) -> dict[int, tuple[int, int]]:
    return {DAYS.index(d): (tmin(a), tmin(b)) for d, (a, b) in v["hours"].items()}


def sales_rows(v: dict) -> list[dict]:
    rows = []
    for d, (o, c) in sorted(open_hours(v).items()):
        for h in range(o // 60, c // 60):
            boost = v.get("doorbuster", {}).get(DAYS[d], {}).get(h, 1)
            txn = round(BASE_TXN[h] * v["txn_mult"][d] * boost)
            online = round(BASE_ONLINE[h] * v["online_mult"][d])
            rows.append({"day": d, "hour": h * 60, "transactions": txn, "online_orders": online,
                         "sales": float(round(txn * AVG_TICKET, 2))})
    return rows


def trucks(v: dict) -> list[dict]:
    return [{"day": DAYS.index(d), "arrival": TRUCK_ARRIVAL, "cases": n} for d, n in v["trucks"].items()]


def plan_rows() -> list[dict]:
    return [{"role": r, "days": days, "start": tmin(s), "end": tmin(e), "headcount": hc} for _, r, days, s, e, hc in PLAN]


def truth(v: dict, slot: int = SLOT) -> ref.SlotMap:
    """The full week at `slot` granularity: standards x sales + plan + trucks."""
    oh = open_hours(v)
    m = ref.sales_to_slots(sales_rows(v), STANDARDS, oh, slot)
    for k, hc in ref.windows_to_slots(plan_rows(), slot).items():
        if k[1] in oh:
            ref.add(m, *k, hc)
    for k, hc in ref.workload_to_slots(trucks(v), UNLOAD, slot).items():
        ref.add(m, *k, hc)
    return m


def truth_15(v: dict) -> ref.SlotMap:
    """15-min truth: cashiers follow the intra-hour transaction shape; everything else as hourly."""
    m = {k: hc for k, hc in truth(v, 15).items() if k[0] != "cashier"}
    cash = next(s for s in STANDARDS if s["role"] == "Cashier")
    for r in sales_rows(v):
        for q, f in enumerate(QUARTER_SHAPE):
            rate = r["transactions"] * f * 4  # transactions per hour at that quarter's pace
            hc = max(cash["min"], min(cash["max"], -(-rate // cash["per"])))
            ref.add(m, "cashier", r["day"], r["hour"] + 15 * q, int(hc))
    return m


def dept_hours(m: ref.SlotMap, slot: int) -> dict[tuple[str, int], Fraction]:
    names = {ref.slug(r): r for r in ROLE_DEPT}
    out: dict[tuple[str, int], Fraction] = {}
    for (rid, day, _), hc in m.items():
        k = (ROLE_DEPT[names[rid]], day)
        out[k] = out.get(k, Fraction(0)) + Fraction(hc * slot, 60)
    return out


def labor_model(v: dict) -> list[dict]:
    """Department -> role shares (whole %, from the normal week's truth) and role windows."""
    m = truth(VARIANTS["normal"])
    by_role: dict[str, Fraction] = {}
    for (rid, _, _), hc in m.items():
        by_role[rid] = by_role.get(rid, Fraction(0)) + hc
    du, op = by_role["drive_up"], by_role["order_pick"]
    du_share = round(100 * du / (du + op))
    win = {"Softlines": ("09:00", "18:00"), "Hardlines": ("09:00", "18:00"), "Truck Unload": ("04:00", "10:00")}
    rows = []
    for role, dept in ROLE_DEPT.items():
        share = du_share if role == "Drive Up" else 100 - du_share if role == "Order Pick" else 100
        s, e = win.get(role, (None, None))
        rows.append({"dept": dept, "role": role, "share": share, "start": tmin(s) if s else None,
                     "end": tmin(e) if e else None})
    return rows


# --------------------------------------------------------------------------- #
def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buf.getvalue())


def fmt_hours(x: Fraction) -> str:
    return f"{float(x):.1f}"


def setup_for(name: str, v: dict) -> dict:
    return {"week_start": v["week_start"].isoformat(), "label": v["label"],
            "hours_by_day": {d: list(h) for d, h in v["hours"].items()},
            "truck_days": {"days": list(v["trucks"]), "start": t24(TRUCK_ARRIVAL)}}


def build(out: Path = HERE) -> None:
    roles_by_slug = {ref.slug(r): r for r in ROLE_DEPT}
    setups = {}
    for name, v in VARIANTS.items():
        ws = v["week_start"]
        setups[name] = setup_for(name, v)
        m30 = truth(v)
        tot = sum(Fraction(hc * SLOT, 60) for hc in m30.values())
        setups[name]["truth_headcount_hours"] = float(tot)

        # 1. per-slot headcount (UKG/Kronos labor forecast), 30-min with explicit end
        rows = [["T2290", (ws + timedelta(days=d)).isoformat(), roles_by_slug[rid], f"{ROLE_DEPT[roles_by_slug[rid]]}-{rid[:4].upper()}",
                 t24(s), t24(s + SLOT), hc] for (rid, d, s), hc in sorted(m30.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2]))]
        write_csv(out / "per_slot_headcount" / f"forecast_30min_{name}.csv",
                  ["Location", "Business Date", "Job", "Labor Code", "Interval Start", "Interval End", "Required Staff"], rows)
        if name in ("normal", "holiday"):
            m15 = truth_15(v)
            rows = [["T2290", (ws + timedelta(days=d)).strftime("%m/%d/%Y"), roles_by_slug[rid], t12(s), 15, hc]
                    for (rid, d, s), hc in sorted(m15.items(), key=lambda kv: (kv[0][1], kv[0][0], kv[0][2]))]
            write_csv(out / "per_slot_headcount" / f"forecast_15min_{name}.csv",
                      ["Location", "Business Date", "Job", "Interval Start", "Interval (min)", "Required Staff"], rows)

        # 3. department x day budgeted hours (wide, with totals)
        dh = dept_hours(m30, SLOT)
        hdr = ["Dept"] + [f"{DAYS[d]} {(ws + timedelta(days=d)).strftime('%m/%d')}" for d in range(7)] + ["Week Total"]
        body = []
        for dept in DEPTS:
            vals = [dh.get((dept, d), Fraction(0)) for d in range(7)]
            body.append([dept] + [fmt_hours(x) for x in vals] + [fmt_hours(sum(vals))])
        day_tot = [sum(dh.get((dept, d), Fraction(0)) for dept in DEPTS) for d in range(7)]
        body.append(["TOTAL"] + [fmt_hours(x) for x in day_tot] + [fmt_hours(sum(day_tot))])
        write_csv(out / "dept_daily_hours" / f"labor_hours_{name}.csv", hdr, body)

        # 4. hourly sales / transactions forecast
        rows = [["T2290", (ws + timedelta(days=r["day"])).isoformat(), t24(r["hour"]), r["transactions"],
                 f"{r['sales']:.2f}", r["online_orders"]] for r in sales_rows(v)]
        write_csv(out / "sales_driven" / f"sales_{name}.csv",
                  ["Store", "Date", "Hour", "Transactions", "Net Sales", "Online Orders"], rows)

        # 5. truck schedule
        if name in ("normal", "holiday"):
            rows = [[(ws + timedelta(days=t["day"])).strftime("%m/%d/%Y"), f"T{k + 1}", "DC 0553", t24(t["arrival"]),
                     t["cases"], t["cases"] * 7] for k, t in enumerate(trucks(v))]
            write_csv(out / "workload_units" / f"trucks_{name}.csv",
                      ["Date", "Truck #", "Origin", "Sched Arrival", "Cases", "Pieces"], rows)

    # shared standards / models
    std_rows = [[s["role"], s["driver"], s["per"] or "", s["min"], s["max"], ""] for s in STANDARDS]
    write_csv(out / "sales_driven" / "labor_standards.csv",
              ["Role", "Driver", "Units per Staff Hour", "Min HC", "Max HC", "Max Duration Hrs"], std_rows)
    write_csv(out / "workload_units" / "unload_standards.csv",
              ["Role", "Driver", "Units per Staff Hour", "Min HC", "Max HC", "Max Duration Hrs"],
              [[UNLOAD["role"], "cases", UNLOAD["per"], UNLOAD["min"], UNLOAD["max"], UNLOAD["max_hours"]]])
    write_csv(out / "dept_daily_hours" / "labor_model.csv", ["Dept", "Role", "Share %", "Window Start", "Window End"],
              [[r["dept"], r["role"], r["share"], t24(r["start"]) if r["start"] is not None else "",
                t24(r["end"]) if r["end"] is not None else ""] for r in labor_model(VARIANTS["normal"])])

    # 2. staffing plan: realistic day ranges, and the same plan one row per day
    v = VARIANTS["normal"]
    plan = [["FRONT END", "Cashier", "Mon-Thu", "08:00", "10:00", 1], ["FRONT END", "Cashier", "Mon-Thu", "10:00", "16:00", 2],
            ["FRONT END", "Cashier", "Mon-Thu", "16:00", "20:00", 3], ["FRONT END", "Cashier", "Mon-Thu", "20:00", "22:00", 1],
            ["FRONT END", "Cashier", "Fri-Sun", "08:00", "10:00", 2], ["FRONT END", "Cashier", "Fri-Sun", "10:00", "20:00", 3],
            ["FRONT END", "Cashier", "Fri-Sun", "20:00", "22:00", 2],
            ["LEADERSHIP", "Leader on Duty", "Daily", "08:00", "22:00", 1],
            ["GUEST SERVICE", "Guest Service", "Daily", "08:00", "22:00", 1],
            ["FULFILLMENT", "Drive Up", "Mon-Sun", "09:00", "21:00", 1],
            ["FULFILLMENT", "Order Pick", "Daily", "07:00", "13:00", 2],
            ["FULFILLMENT", "Order Pick", "Daily", "13:00", "17:00", 1]] + \
           [[dept, r, days, s, e, hc] for dept, r, days, s, e, hc in PLAN] + \
           [["FLOW", "Truck Unload", "Tue/Thu/Sat", "04:00", "10:00", 4]]
    write_csv(out / "windowed_roles" / "staffing_plan_ranges.csv",
              ["Dept", "Role", "Days", "Start", "End", "Headcount"], plan)
    per_day = [[dept, r, DAYS[d], t12(tmin(s)), t12(tmin(e)), hc] for dept, r, days, s, e, hc in plan
               for d in ref.parse_days(days)]
    write_csv(out / "windowed_roles" / "staffing_plan_per_day.csv",
              ["Dept", "Role", "Day", "Start", "End", "Headcount"], per_day)
    write_csv(out / "windowed_roles" / "softlines_hardlines_plan.csv", ["Dept", "Role", "Day", "Start", "End", "Headcount"],
              [[dept, r, DAYS[d], s, e, hc] for dept, r, days, s, e, hc in PLAN for d in ref.parse_days(days)])
    write_csv(out / "windowed_roles" / "truck_override.csv", ["Dept", "Role", "Day", "Start", "End", "Headcount"],
              [["FLOW", "Truck Unload", d, "04:00", "09:00", 5] for d in ("Tue", "Thu", "Sat")])
    setups["_shared"] = {
        "_what": "Leader setup per week variant (store_basics: week + hours; pre-open 240 for 4am trucks). "
                 "Load corporate_mid_tx roster/training/availability first.",
        "base_pack": "corporate_mid_tx", "slot_minutes": SLOT, "pre_open_minutes": 240,
        "timezone": "America/Chicago", "jurisdiction": {"state": "TX", "city": None},
    }
    (out / "week_variants.json").write_text(json.dumps(setups, indent=2) + "\n")


if __name__ == "__main__":
    build()
    print("wrote demand packs under", HERE)
