"""Acceptance tests for the CSV import packs, through the real API (create_app + TestClient, no LLM).

Tests marked `xfail` document importer bugs/limitations found with these packs (listed for WS6 in
README.md). They assert the behaviour we WANT; they start passing (XPASS, not an error) once fixed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util  # noqa: E402

import packs_harness as h  # noqa: E402

_spec = importlib.util.spec_from_file_location("import_packs_build", Path(__file__).resolve().parent / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

HERE = h.HERE
bug = pytest.mark.xfail(strict=False)


def _emps(cfg: dict) -> dict[str, dict]:
    return {e["id"]: e for e in cfg["employees"]}


def _unavail(e: dict, wd: int) -> list[tuple[int, int]]:
    return sorted((a["start"], a["end"]) for a in e["availability"] if a.get("weekday") == wd and a["kind"] == "unavailable")


def _skipped(res: h.ImportResult) -> list[str]:
    return [w for w in res.warnings if "skipped" in w]


# --------------------------------------------------------------------------- #
def test_build_is_reproducible(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "HERE", tmp_path)
    build.clean_small_tx(), build.corporate_mid_tx(), build.messy_mid_ca(), build.edge_cases()
    made = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert made, "build wrote nothing"
    for rel in made:
        assert (HERE / rel).read_bytes() == (tmp_path / rel).read_bytes(), f"{rel} is stale: re-run build.py"


def test_phones_are_fake_555_01xx():
    import re
    for p in HERE.glob("*/*.csv"):
        for m in re.finditer(rb"555[-. ]?(\d{4})", p.read_bytes()):
            assert m.group(1).startswith(b"01"), (p, m.group(0))


# --------------------------------------------------------------------------- #
# clean_small_tx: everything auto-maps, readiness green, solve validates
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def clean():
    s, res = h.run_pack("clean_small_tx")
    return s, res, s.config()


def test_clean_auto_maps_and_imports_everything(clean):
    s, res, cfg = clean
    for kind, r in res.items():
        assert r.status == 200 and r.preview["unmapped_required"] == [], kind
        assert r.commit_status == 200, (kind, r.commit_detail)
        assert _skipped(r) == [], (kind, r.warnings)
    assert len(cfg["employees"]) == 15
    assert {r["id"] for r in cfg["roles"]} == {"leader_on_duty", "guest_service_desk", "cashier", "drive_up", "softlines"}
    e = _emps(cfg)
    assert e["1001"]["phone"] == "+15125550100" and e["1001"]["status"] == "full_time" and e["1001"]["age"] == 38
    assert e["1006"]["age"] == 17
    assert _unavail(e["1005"], 0) == [(0, 900), (1260, 1440)]  # student: 3pm-9pm weekdays
    assert _unavail(e["1007"], 2) == [(0, 1440)]               # OFF
    assert len(s.app.state.db.get(s.sid, "history", "rows")) == res["history"].preview["row_count"]


@pytest.mark.slow
def test_clean_readiness_and_solve(clean):
    s, _, _ = clean
    rd = s.readiness()
    assert rd["ready"], h.failing_checks(rd)
    out = h.summarize(s.solve())
    assert out["validator_passed"], out
    assert out["status"] in ("optimal", "feasible")
    assert out["coverage_pct"] >= 90, out


def test_bug_readiness_flags_zero_priority_roles():
    """Imported roles get $0/h gap penalty. Without the leader's priorities step readiness is still green,
    and /solve returns an empty schedule (0 shifts, 0% coverage) that the validator passes."""
    setup = dict(h.load_setup("clean_small_tx"), gap_penalty_per_hour={})
    s = h.Session()
    s.create(setup)
    s.store_basics(setup)
    for kind in h.KINDS:
        s.import_file(kind, HERE / "clean_small_tx" / f"{kind}.csv")
    s.priorities_and_budget(setup)
    assert not s.readiness()["ready"]


def test_clean_on_bigbox_small_template_resolves_role_names():
    """Same CSVs into the bigbox_small template: role names match the template, so no new roles."""
    setup = dict(h.load_setup("clean_small_tx"), template="bigbox_small")
    s = h.Session()
    s.create(setup)
    s.store_basics(setup)
    for kind in h.KINDS:
        r = s.import_file(kind, HERE / "clean_small_tx" / f"{kind}.csv")
        assert r.commit_status == 200
        assert not [w for w in r.warnings if "Unknown role" in w], r.warnings
    rd = s.readiness()
    # template roles the store doesn't use (hardlines, fitting_room, ...) have nobody trained -> blocks
    assert not rd["ready"] and "training" in h.failing_checks(rd)


# --------------------------------------------------------------------------- #
# corporate_mid_tx: Workday/Kronos headers, two manual mappings, truck days
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def corp():
    s, res = h.run_pack("corporate_mid_tx")
    return s, res, s.config()


def test_corporate_mappings(corp):
    _, res, _ = corp
    assert res["roster"].preview["unmapped_required"] == ["home_department"]
    assert res["roster"].preview["proposed_mapping"]["Home Org"] is None
    assert res["roster"].preview["proposed_mapping"]["Legal Name"] == "name"
    assert res["roster"].preview["proposed_mapping"]["Pay Rate"] == "wage_per_hour"
    assert res["history"].preview["unmapped_required"] == ["start"]
    assert res["history"].preview["proposed_mapping"]["Punch Out"] == "end"
    for kind in ("training", "availability", "forecast"):
        assert res[kind].preview["unmapped_required"] == [], kind
    for kind, r in res.items():
        assert r.commit_status == 200, (kind, r.commit_detail)
        assert _skipped(r) == [], (kind, r.warnings)


def test_corporate_config(corp):
    _, _, cfg = corp
    e = _emps(cfg)
    assert len(e) == 40 and "0048100" in e  # zero-padded ids survive across all files
    assert all(x["trained_role_ids"] for x in e.values())
    assert len(cfg["departments"]) == 7 and len(cfg["roles"]) == 8
    truck = [d for d in cfg["demand"] if d["role_id"] == "truck_unload"]
    assert sorted((d["day"], d["start"], d["end"], d["headcount"]) for d in truck) == \
        [(1, 240, 600, 4), (3, 240, 600, 4), (5, 240, 600, 4)]
    assert {x["status"] for x in e.values()} == {"full_time", "part_time", "seasonal"}
    assert e["0048100"]["wage_per_hour"] == 24.25 and e["0048100"]["max_hours_week"] == 40


@pytest.mark.slow
def test_corporate_readiness_and_solve(corp):
    s, _, _ = corp
    rd = s.readiness()
    assert rd["ready"], h.failing_checks(rd)
    out = h.summarize(s.solve())
    assert out["validator_passed"], out
    assert out["coverage_pct"] >= 80, out


# --------------------------------------------------------------------------- #
# messy_mid_ca: planted problems must surface
# --------------------------------------------------------------------------- #
MINOR, LOW_WAGE, BAD_YEAR, BAD_DOB, NO_AREA, DUP = "2219", "2212", "2223", "2224", "2225", "2207"


@pytest.fixture(scope="module")
def messy():
    s, res = h.run_pack("messy_mid_ca")
    return s, res, s.config()


def test_messy_roster(messy):
    _, res, cfg = messy
    r = res["roster"]
    assert r.commit_status == 200
    e = _emps(cfg)
    assert len(e) == 24                                       # 25 people, one lost to an unreadable DOB
    assert BAD_DOB not in e
    assert sum("empty employee id" in w for w in r.warnings) == 2
    assert any("March 3, 1999" in w for w in r.warnings)
    assert e[DUP]["wage_per_hour"] == 18.25                    # duplicate row: last one wins
    assert {x["home_department_id"] for x in e.values()} == {"leadership", "front_end", "softlines", "hardlines", "flow"}
    assert e["2203"]["wage_per_hour"] == 23.75 and e["2204"]["wage_per_hour"] == 26.0
    assert e[MINOR]["age"] == 16
    assert e["2204"]["age"] == 47                              # 08/16/79 -> 1979, right
    assert e[NO_AREA]["phone"] == "+5550185"                   # kept as-is (see bug test below)


def test_messy_training_and_availability(messy):
    _, res, cfg = messy
    e = _emps(cfg)
    assert "forklift" in e[MINOR]["trained_role_ids"]
    assert set(e["2201"]["trained_role_ids"]) >= {"lod", "gsa", "cashier"}  # "GSA; CASHIER" split
    tw = res["training"].warnings
    assert any("'2215.0'" in w for w in tw) and any("'9999'" in w for w in tw)
    assert e["2215"]["trained_role_ids"] == []
    aw = res["availability"].warnings
    assert any("Not Available" in w for w in aw) and any("after 4pm" in w for w in aw)
    assert any("'8888'" in w for w in aw)
    assert _unavail(e["2203"], 0) == [(0, 1440)]               # OFF
    assert _unavail(e["2204"], 5) == [(0, 1440)]               # N/A
    assert _unavail(e["2205"], 0) == [(0, 540), (1020, 1440)]  # 9a-5p
    assert _unavail(e["2208"], 3) == [(0, 480), (720, 1020), (1260, 1440)]  # two windows


def test_messy_forecast_and_history(messy):
    _, res, cfg = messy
    assert any("'BEAUTY'" in w for w in res["forecast"].warnings)
    assert {d["day"] for d in cfg["demand"]} == set(range(7))  # Mon/Tuesday/ISO/Thurs/US date/Sat/Sunday
    hist = res["history"]
    assert hist.preview["columns"] == ["Kronos Workforce Central - Punch Detail Report"]
    assert set(hist.preview["unmapped_required"]) == {"employee_id", "date", "start", "end"}
    assert hist.commit_status == 422


def test_messy_readiness_blocks(messy):
    s, _, _ = messy
    rd = s.readiness()
    fails = h.failing_checks(rd)
    assert not rd["ready"]
    assert set(fails) == {"training", "minimum_wage"}, fails
    assert "beauty" in fails["training"].lower()
    assert "$16.90" in fails["minimum_wage"] and "$15.50" in fails["minimum_wage"]


def _apply_fixes(s: h.Session, tag_pit: bool) -> None:
    fx = h.load_setup("messy_mid_ca")["fixes_after_review"]
    cfg = s.config()
    for e in cfg["employees"]:
        e["wage_per_hour"] = fx["wage"].get(e["id"], e["wage_per_hour"])
        e["age"] = fx["age"].get(e["id"], e["age"])
        e["phone"] = fx["phone"].get(e["id"], e["phone"])
        e["trained_role_ids"] += [r for r in fx["train"].get(e["id"], []) if r not in e["trained_role_ids"]]
    for r in cfg["roles"]:
        r["gap_penalty_per_hour"] = fx["gap_penalty"].get(r["id"], r["gap_penalty_per_hour"])
    if tag_pit:
        cfg["role_tags"].update(fx["role_tags"])
        for r in cfg["roles"]:
            r["min_age"] = fx["role_min_age"].get(r["id"], r["min_age"])
    s.put(cfg)


@pytest.fixture(scope="module")
def messy_solves(messy):
    """Leader fixes the review items, solves; then also tags FORKLIFT as a PIT role and solves again."""
    s, _, _ = messy
    _apply_fixes(s, tag_pit=False)
    ready = s.readiness()
    untagged = s.solve()
    _apply_fixes(s, tag_pit=True)
    return ready, untagged, s.solve()


@pytest.mark.slow
def test_messy_ready_after_review_fixes(messy_solves):
    ready, untagged, _ = messy_solves
    assert ready["ready"], h.failing_checks(ready)
    assert untagged["validation"]["passed"], h.summarize(untagged)


@pytest.mark.slow
def test_messy_minor_never_on_forklift_once_tagged(messy_solves):
    _, _, tagged = messy_solves
    assert tagged["validation"]["passed"], h.summarize(tagged)
    assert MINOR not in h.role_assignments(tagged, "forklift")
    assert h.role_assignments(tagged, "forklift")  # adults still cover it


@pytest.mark.slow
def test_bug_minor_on_untagged_forklift(messy_solves):
    """Without the leader's manual tag the engine schedules the 16-year-old on FORKLIFT and the
    validator passes it (neither can know the imported role is a powered industrial truck)."""
    _, untagged, _ = messy_solves
    assert MINOR not in h.role_assignments(untagged, "forklift")


# --- importer bugs found with the messy pack (desired behaviour; xfail until WS6 fixes) ---
def test_bug_manager_column_not_mapped_to_age(messy):
    _, res, _ = messy
    assert res["roster"].preview["proposed_mapping"]["Manager"] != "age"


def test_bug_imported_pit_role_is_protected(messy):
    """A role named FORKLIFT/PIT imported into an empty store gets no role_tags and min_age 0, so the
    federal minor_prohibited_roles rule can't see it (engine and validator both rely on tags/min_age)."""
    s, _, _ = messy
    fresh = h.Session()
    h.run_pack("messy_mid_ca", fresh)
    cfg = fresh.config()
    role = next(r for r in cfg["roles"] if r["id"] == "forklift")
    assert role["min_age"] >= 18 or "powered_industrial_truck" in cfg["role_tags"].get("forklift", [])


def test_bug_duplicate_employee_rows_warned(messy):
    _, res, _ = messy
    assert any(DUP in w and "duplicate" in w.lower() for w in res["roster"].warnings)


def test_bug_two_digit_birth_year_gives_sane_age(messy):
    _, _, cfg = messy
    assert all(14 <= e["age"] <= 100 for e in cfg["employees"]), \
        [(e["id"], e["age"]) for e in cfg["employees"] if not 14 <= e["age"] <= 100]


def test_bug_seas_status_is_seasonal(messy):
    _, _, cfg = messy
    assert _emps(cfg)["2213"]["status"] == "seasonal"


def test_bug_bad_phone_warned(messy):
    _, res, _ = messy
    assert any(NO_AREA in w and "phone" in w.lower() for w in res["roster"].warnings)


def test_bug_not_available_means_unavailable(messy):
    _, _, cfg = messy
    assert _unavail(_emps(cfg)["2213"], 0) == [(0, 1440)]


def test_bug_hourly_forecast_rows_cover_the_hour(messy):
    _, _, cfg = messy
    lod_mon = sorted((d["start"], d["end"]) for d in cfg["demand"] if d["role_id"] == "lod" and d["day"] == 0)
    assert lod_mon == [(480, 1320)], lod_mon[:4]


def test_bug_fractional_headcount_warned(messy):
    _, res, _ = messy
    assert any("0.5" in w or "1.5" in w for w in res["forecast"].warnings)


def test_bug_commit_returns_row_warnings(messy):
    """Commit-time warnings (skipped rows, unknown ids, new roles) are stored but not returned, so the UI
    never shows them. Desired: the commit response (or a GET) exposes them."""
    s, _, _ = messy
    paths = {r.path for r in s.app.routes if hasattr(r, "path")}
    assert any("import" in p and "warning" in p for p in paths)


# --------------------------------------------------------------------------- #
# edge_cases: one importer edge per file
# --------------------------------------------------------------------------- #
EDGE = HERE / "edge_cases"


@pytest.fixture
def edge():
    s = h.Session()
    setup = {"template": "empty", "name": "Edge", "jurisdiction": {"state": "TX", "city": None},
             "timezone": "America/Chicago", "slot_minutes": 30, "hours": {"open": "08:00", "close": "22:00"}}
    s.create(setup)
    s.store_basics(setup)
    assert s.import_file("roster", EDGE / "roster_base.csv").commit_status == 200
    return s


def test_edge_bom_header(edge):
    r = edge.import_file("roster", EDGE / "roster_bom.csv")
    assert r.preview["columns"][0] == "Employee ID" and r.commit_status == 200
    assert "E3" in _emps(edge.config())


def test_edge_first_last_and_age(edge):
    r = edge.import_file("roster", EDGE / "roster_first_last_age.csv")
    assert r.preview["unmapped_required"] == [] and r.commit_status == 200
    e = _emps(edge.config())["E4"]
    assert (e["name"], e["age"], e["phone"], e["wage_per_hour"]) == ("Dana Underhill", 45, "+15125550193", 16.0)


def test_edge_missing_required_column(edge):
    r = edge.import_file("roster", EDGE / "roster_missing_wage.csv")
    assert r.preview["unmapped_required"] == ["wage_per_hour"] and r.commit_status == 422


def test_edge_header_only(edge):
    r = edge.import_file("roster", EDGE / "roster_header_only.csv")
    assert r.preview["row_count"] == 0 and any("no data rows" in w for w in r.preview["warnings"])
    assert r.commit_status == 400


def test_edge_utf8_names(edge):
    edge.import_file("roster", EDGE / "roster_utf8_names.csv")
    assert _emps(edge.config())["E6"]["name"] == "José Núñez-Ortíz"


def test_edge_training_list_in_one_cell(edge):
    edge.import_file("training", EDGE / "training_list_in_cell.csv")
    e = _emps(edge.config())
    assert e["E1"]["trained_role_ids"] == ["cashier", "drive_up", "guest_service_desk"]
    assert e["E2"]["trained_role_ids"] == ["cashier", "drive_up"]


def test_edge_overnight_availability(edge):
    edge.import_file("availability", EDGE / "availability_overnight.csv")
    e = _emps(edge.config())
    assert _unavail(e["E1"], 0) == [(0, 1320)]   # 22:00-06:00: free from 22:00 (next morning not modelled)
    assert _unavail(e["E2"], 0) == [(0, 1080)]   # 6pm-12am
    assert _unavail(e["E1"], 1) == [(0, 1440)] and _unavail(e["E2"], 1) == [(0, 1440)]


def test_edge_overnight_forecast_window(edge):
    edge.import_file("forecast", EDGE / "forecast_overnight_window.csv")
    assert [(d["day"], d["start"], d["end"]) for d in edge.config()["demand"]] == [(4, 1320, 1800)]


def test_bug_overnight_forecast_end_column(edge):
    r = edge.import_file("forecast", EDGE / "forecast_overnight_end_column.csv")
    assert r.commit_status == 200
    assert [(d["start"], d["end"]) for d in edge.config()["demand"]] == [(1320, 1800)]


def test_edge_15min_forecast_in_15min_store(edge):
    cfg = edge.config()
    cfg["store"]["slot_minutes"] = 15
    edge.put(cfg)
    edge.import_file("forecast", EDGE / "forecast_15min_slots.csv")
    got = [(d["start"], d["end"], d["headcount"]) for d in edge.config()["demand"]]
    assert got == [(600, 615, 2), (615, 645, 3), (645, 675, 2), (675, 705, 3), (705, 720, 2)]


def test_bug_15min_forecast_in_30min_store_flagged(edge):
    r = edge.import_file("forecast", EDGE / "forecast_15min_slots.csv")
    slot = edge.config()["store"]["slot_minutes"]
    off_grid = [d for d in edge.config()["demand"] if d["start"] % slot or d["end"] % slot]
    assert r.commit_status != 200 or not off_grid or any("slot" in w for w in r.warnings)


def test_bug_hourly_start_only_rows(edge):
    edge.import_file("forecast", EDGE / "forecast_hourly_start_only.csv")
    assert [(d["start"], d["end"]) for d in edge.config()["demand"]] == [(600, 780)]


def test_bug_forecast_dates_outside_week_warned(edge):
    r = edge.import_file("forecast", EDGE / "forecast_other_week_dates.csv")
    assert r.commit_status != 200 or any("week" in w for w in r.warnings)


def test_bug_fractional_headcount(edge):
    r = edge.import_file("forecast", EDGE / "forecast_fractional_hc.csv")
    assert any("0.5" in w or "1.6" in w for w in r.warnings)


def test_edge_history_formats(edge):
    r = edge.import_file("history", EDGE / "history_basic.csv")
    assert r.commit_status == 200 and _skipped(r) == []
    rows = edge.app.state.db.get(edge.sid, "history", "rows")
    assert [(x["date"], x["start"], x["end"]) for x in rows] == [("2026-11-02", 480, 990), ("2026-11-02", 780, 1260)]
