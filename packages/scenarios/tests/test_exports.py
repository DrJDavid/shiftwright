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


# --- every sector exports (E1: food raised KeyError 'management') ---

from shiftwright_scenarios import DIFFICULTIES, generate  # noqa: E402
from shiftwright_scenarios.exports import DEPT_CODES, JOB_CODES  # noqa: E402

SECTORS = ["retail", "food"]


def _read(d, name):
    with (d / name).open() as f:
        return list(csv.DictReader(f))


@pytest.mark.parametrize("sector", SECTORS)
@pytest.mark.parametrize("size", ["S", "M", "L"])
@pytest.mark.parametrize("diff", DIFFICULTIES)
def test_generated_scenarios_export_every_sector(sector, size, diff, tmp_path):
    sc = generate(1, size, diff, "IL/chicago", sector=sector)
    write_exports(sc, tmp_path)
    cfg = sc.config
    code_to_role = {v: k for k, v in JOB_CODES.items()}
    code_to_dept = {v: k for k, v in DEPT_CODES.items()}
    roster = _read(tmp_path, "roster.csv")
    assert [r["TM_ID"] for r in roster] == [tm_id(e.id) for e in cfg.employees]
    assert [code_to_dept[r["Dept"]] for r in roster] == [e.home_department_id for e in cfg.employees]
    training = _read(tmp_path, "training.csv")
    assert [code_to_role[r["Job Code"]] for r in training] == [r for e in cfg.employees for r in e.trained_role_ids]
    forecast = _read(tmp_path, "forecast.csv")
    assert len(forecast) == len(cfg.demand)
    assert {code_to_role[r["Job Code"]] for r in forecast} == {d.role_id for d in cfg.demand}
    assert {code_to_dept[r["Dept"]] for r in forecast} <= {d.id for d in cfg.departments}
    history = _read(tmp_path, "history.csv")
    assert len(history) == sum(len(s.segments) for w in sc.history for s in w.shifts)
    assert {code_to_role[r["Job Code"]] for r in history} <= {r.id for r in cfg.roles}


def test_food_forecast_driver_names_the_event(tmp_path):
    sc = generate(1, "M", "normal", "IL/chicago", sector="food")
    write_exports(sc, tmp_path)
    drivers = {r["Driver"] for r in _read(tmp_path, "forecast.csv")}
    assert "EVENT" in drivers and "FREIGHT" not in drivers


def test_demo_restaurant_exports(tmp_path):
    sc = load_demo_scenario("restaurant")
    write_exports(sc, tmp_path)
    assert len(_read(tmp_path, "roster.csv")) == len(sc.config.employees)


def test_codes_are_unique():
    assert len(set(JOB_CODES.values())) == len(JOB_CODES)
    assert len(set(DEPT_CODES.values())) == len(DEPT_CODES)
