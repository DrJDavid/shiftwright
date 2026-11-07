"""Acceptance tests for the demo CSV exports (WS4 deliverable 4)."""
import csv
from datetime import datetime

import pytest

from shiftwright_scenarios import FIXTURES_DIR, load_demo_scenario
from shiftwright_scenarios.exports import tm_id, write_exports

EXPORTS = FIXTURES_DIR / "exports"
FILES = ["roster.csv", "training.csv", "availability.csv", "forecast.csv", "history.csv"]
OUR_FIELDS = {"id", "name", "employee_id", "role_id", "wage_per_hour", "home_department_id", "trained_role_ids",
              "age", "status", "day", "start", "end", "headcount", "availability"}


@pytest.fixture(scope="module")
def sc():
    return load_demo_scenario()


def _rows(name):
    with (EXPORTS / name).open() as f:
        return list(csv.DictReader(f))


def test_committed_exports_match_builder(sc, tmp_path):
    write_exports(sc, tmp_path)
    for name in FILES:
        assert (tmp_path / name).read_bytes() == (EXPORTS / name).read_bytes(), name


def test_headers_dont_match_our_field_names():
    for name in FILES:
        with (EXPORTS / name).open() as f:
            header = next(csv.reader(f))
        assert not {h.lower() for h in header} & OUR_FIELDS, (name, header)
    assert "Wage Rate" in _rows("roster.csv")[0]
    assert "Avail Mon" in _rows("availability.csv")[0]


def test_row_counts_round_trip(sc):
    cfg = sc.config
    assert len(_rows("roster.csv")) == len(cfg.employees)
    assert len(_rows("availability.csv")) == len(cfg.employees)
    assert len(_rows("training.csv")) == sum(len(e.trained_role_ids) for e in cfg.employees)
    assert len(_rows("forecast.csv")) == len(cfg.demand)
    assert len(_rows("history.csv")) == sum(len(s.segments) for w in sc.history for s in w.shifts)


def test_dob_gives_age_and_forecast_hours(sc):
    cfg = sc.config
    ws = cfg.store.week_start
    by_tm = {r["TM_ID"]: r for r in _rows("roster.csv")}
    for e in cfg.employees:
        dob = datetime.strptime(by_tm[tm_id(e.id)]["DOB"], "%m/%d/%Y").date()
        age = ws.year - dob.year - ((ws.month, ws.day) < (dob.month, dob.day))
        assert age == e.age, e.id
    hc_hours = 0.0
    for r in _rows("forecast.csv"):
        s = datetime.strptime(r["Start Time"], "%I:%M %p")
        e = datetime.strptime(r["End Time"], "%I:%M %p")
        mins = (e - s).seconds // 60 or 1440
        hc_hours += int(r["Req HC"]) * mins / 60
    assert hc_hours == pytest.approx(sc.expected["required_hours"])
