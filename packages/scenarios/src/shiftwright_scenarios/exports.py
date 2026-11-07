"""CSV exports in "corporate system export" style. Column names and value formats deliberately
don't match our fields, so the import mapping step has real work to do:

roster.csv        TM_ID, Full Name, Dept, Job Status, Wage Rate, Hire Date, DOB, Min Hrs, Max Hrs, Phone
training.csv      TM_ID, Job Code, Job Desc, Cert Date
availability.csv  TM_ID, Avail Mon .. Avail Sun, Pref Off
forecast.csv      Date, Dept, Job Code, Start Time, End Time, Req HC, Driver
history.csv       Week Ending, Date, TM_ID, Job Code, In, Out

Mapping notes (for the importer):
  TM_ID = "7" + 5-digit employee number (e007 -> 700007). Dept/Job Code tables are DEPT_CODES /
  JOB_CODES below. Job Status FT/PT/SEAS. Wage Rate "$16.25". Dates MM/DD/YYYY. DOB gives the
  employee's age on week_start. Driver is FREIGHT (truck/delivery event), EVENT (any other event),
  ONLINE (order_picker/drive_up) or SALES. Avail values: "ALL", "NOT AVAIL", or "HHMM-HHMM" windows
  joined by ";". Forecast/History times are 12-hour clock ("4:00 AM").
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from shiftwright_contracts.models import AvailabilityKind, Employee, EventKind, StoreConfig

from .catalog import DAY_NAMES
from .models import Scenario

DEPT_CODES = {
    "front_of_store": "FRONT END",
    "general_merchandise": "GENERAL MDSE",
    "grocery": "FOOD",
    "fulfillment": "FULFILLMENT",
    "asset_protection": "ASSET PROT",
    "receiving": "INBOUND",
    "leadership": "LEADERSHIP",
    "front_of_house": "FOH",
    "back_of_house": "BOH",
    "management": "MGMT",
}
JOB_CODES = {
    "leader_on_duty": "LOD",
    "guest_service_desk": "GSD",
    "cashier": "CASH",
    "cart_attendant": "CART",
    "drive_up": "DRVUP",
    "softlines": "SFTL",
    "hardlines": "HRDL",
    "fitting_room": "FITRM",
    "grocery_stock": "GROC",
    "order_picker": "OPU",
    "ap_specialist": "AP",
    "truck_unload": "INBD",
    "backroom": "BKRM",
    "pit_operator": "PIT",
    "manager_on_duty": "MOD",
    "server": "SRVR",
    "bartender": "BAR",
    "host": "HOST",
    "line_cook": "LINE",
    "prep_cook": "PREP",
    "dishwasher": "DISH",
}
STATUS_CODES = {"full_time": "FT", "part_time": "PT", "seasonal": "SEAS"}


def tm_id(emp_id: str) -> str:
    return f"7{int(emp_id.lstrip('e')):05d}"


def _d(x: date) -> str:
    return x.strftime("%m/%d/%Y")


def _t12(m: int) -> str:
    m %= 1440
    h, mm = divmod(m, 60)
    return f"{h % 12 or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}{m % 60:02d}"


def _phone(p: str) -> str:
    d = p.removeprefix("+1")
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else p


def _dob(e: Employee, week_start: date) -> date:
    """A birthday consistent with e.age on week_start (deterministic per employee id)."""
    offset = random.Random(f"dob|{e.id}").randint(1, 360)
    return date(week_start.year - e.age, week_start.month, week_start.day) - timedelta(days=offset)


def _avail(e: Employee, weekday: int) -> str:
    blocks = sorted((a.start, a.end) for a in e.availability
                    if a.kind == AvailabilityKind.unavailable and a.weekday == weekday)
    if not blocks:
        return "ALL"
    free, t = [], 0
    for s, en in blocks:
        if s > t:
            free.append((t, s))
        t = max(t, en)
    if t < 1440:
        free.append((t, 1440))
    return ";".join(f"{_hhmm(s)}-{_hhmm(en)}" for s, en in free) or "NOT AVAIL"


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write_exports(sc: Scenario, out_dir: Path) -> None:
    cfg: StoreConfig = sc.config
    out_dir.mkdir(parents=True, exist_ok=True)
    ws = cfg.store.week_start
    role_dept = {r.id: r.department_id for r in cfg.roles}
    role_name = {r.id: r.name for r in cfg.roles}
    event_kind = {ev.id: ev.kind for ev in cfg.events}

    def driver(d) -> str:
        if d.event_id:
            return "FREIGHT" if event_kind.get(d.event_id) in (EventKind.truck, EventKind.delivery) else "EVENT"
        return "ONLINE" if d.role_id in ("order_picker", "drive_up") else "SALES"

    _write(out_dir / "roster.csv",
           ["TM_ID", "Full Name", "Dept", "Job Status", "Wage Rate", "Hire Date", "DOB", "Min Hrs", "Max Hrs", "Phone"],
           [[tm_id(e.id), e.name, DEPT_CODES[e.home_department_id], STATUS_CODES[e.status.value],
             f"${e.wage_per_hour:.2f}", _d(e.hire_date), _d(_dob(e, ws)), f"{e.min_hours_week:g}",
             f"{e.max_hours_week:g}", _phone(e.phone)] for e in cfg.employees])

    _write(out_dir / "training.csv", ["TM_ID", "Job Code", "Job Desc", "Cert Date"],
           [[tm_id(e.id), JOB_CODES[r], role_name[r].upper(),
             _d(max(e.hire_date, ws - timedelta(days=random.Random(f"cert|{e.id}|{r}").randint(14, 900))))]
            for e in cfg.employees for r in e.trained_role_ids])

    _write(out_dir / "availability.csv", ["TM_ID"] + [f"Avail {d[:3]}" for d in DAY_NAMES] + ["Pref Off"],
           [[tm_id(e.id)] + [_avail(e, wd) for wd in range(7)]
            + [";".join(DAY_NAMES[a.weekday][:3] for a in e.availability
                        if a.kind == AvailabilityKind.preferred_off and a.weekday is not None)]
            for e in cfg.employees])

    _write(out_dir / "forecast.csv", ["Date", "Dept", "Job Code", "Start Time", "End Time", "Req HC", "Driver"],
           [[_d(ws + timedelta(days=d.day)), DEPT_CODES[role_dept[d.role_id]], JOB_CODES[d.role_id],
             _t12(d.start), _t12(d.end), d.headcount, driver(d)]
            for d in sorted(cfg.demand, key=lambda d: (d.day, d.start, d.role_id))])

    rows = []
    for wk in sc.history:
        week_end = wk.week_start + timedelta(days=6)
        for s in sorted(wk.shifts, key=lambda s: (s.day, s.start, s.employee_id)):
            for g in s.segments:
                rows.append([_d(week_end), _d(wk.week_start + timedelta(days=s.day)), tm_id(s.employee_id),
                             JOB_CODES[g.role_id], _t12(g.start), _t12(g.end)])
    _write(out_dir / "history.csv", ["Week Ending", "Date", "TM_ID", "Job Code", "In", "Out"], rows)
