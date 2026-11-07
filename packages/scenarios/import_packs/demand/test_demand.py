"""Demand-import packs through the real API (create_app + TestClient, no LLM).

Plain tests record what the importer does TODAY. `xfail` tests encode the conversions specified in
demand/README.md (expected numbers come from spec_reference.py) so WS6 can turn them green.
Proposed import kinds are constants below; if WS6 picks other names, change them here.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from fractions import Fraction
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import packs_harness as h  # noqa: E402
import spec_reference as ref  # noqa: E402

_spec = importlib.util.spec_from_file_location("demand_build", HERE / "build_demand.py")
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)

KIND_LABOR_MODEL = "labor_model"
KIND_LABOR_HOURS = "labor_hours"
KIND_STANDARDS = "labor_standards"
KIND_SALES = "sales_forecast"
KIND_WORKLOAD = "workload"

VARIANTS = json.loads((HERE / "week_variants.json").read_text())
CORP = h.HERE / "corporate_mid_tx"
bug = pytest.mark.xfail(strict=False)
spec = pytest.mark.xfail(strict=False, reason="conversion not implemented yet (spec in demand/README.md)")


def base_session(variant: str, slot: int = 30) -> h.Session:
    """corporate_mid_tx people (roster, training, availability) in the variant's week, no demand yet."""
    corp = h.load_setup("corporate_mid_tx")
    v = VARIANTS[variant]
    setup = dict(corp, week_start=v["week_start"], hours_by_day=v["hours_by_day"], slot_minutes=slot,
                 weekly_hours_cap=round(v["truth_headcount_hours"]),
                 truck_days={"days": v["truck_days"]["days"], "start": "04:00", "end": "10:00"})
    s = h.Session()
    s.create(setup)
    s.store_basics(setup)
    for kind in ("roster", "training", "availability"):
        r = s.import_file(kind, CORP / f"{kind}.csv", corp["manual_mappings"].get(kind))
        assert r.commit_status == 200, (kind, r.commit_detail)
    s.priorities_and_budget(setup)
    return s


def slot_map(s: h.Session) -> ref.SlotMap:
    return ref.config_slot_map(s.config())


def open_hours(variant: str) -> dict[int, tuple[int, int]]:
    return bd.open_hours(bd.VARIANTS[variant])


def commit_kind(s: h.Session, kind: str, path: Path, overrides: dict | None = None) -> h.ImportResult:
    r = s.import_file(kind, path, overrides)
    assert r.status == 200, (kind, r.preview)
    assert r.commit_status == 200, (kind, r.commit_detail)
    return r


# --------------------------------------------------------------------------- #
def test_build_is_reproducible(tmp_path):
    bd.build(tmp_path)
    made = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert len(made) > 20
    for rel in made:
        assert (HERE / rel).read_bytes() == (tmp_path / rel).read_bytes(), f"{rel} is stale: re-run build_demand.py"


def test_styles_describe_the_same_week():
    """Internal consistency: dept hours = per-slot headcount-hours; trucks match the per-slot truck rows."""
    for name, v in bd.VARIANTS.items():
        m = bd.truth(v)
        assert float(sum(Fraction(hc * 30, 60) for hc in m.values())) == VARIANTS[name]["truth_headcount_hours"]
        trucks = {k: hc for k, hc in m.items() if k[0] == "truck_unload"}
        assert trucks == ref.workload_to_slots(bd.trucks(v), bd.UNLOAD, 30)
    hol = bd.truth(bd.VARIANTS["holiday"])
    assert not [k for k in hol if k[1] == 3], "Thanksgiving is closed"
    assert min(k[2] for k in hol if k[1] == 4 and k[0] == "cashier") == 360  # Black Friday opens 06:00


# --------------------------------------------------------------------------- #
# 1. per_slot_headcount: works today (30-min with end; 15-min in a 15-min store)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("variant", ["normal", "holiday", "promo", "light_january"])
def test_per_slot_30min_imports_exactly(variant):
    s = base_session(variant)
    r = commit_kind(s, "forecast", HERE / "per_slot_headcount" / f"forecast_30min_{variant}.csv")
    assert r.preview["unmapped_required"] == []
    assert not [w for w in r.warnings if "skipped" in w or "Unknown role" in w], r.warnings
    assert slot_map(s) == bd.truth(bd.VARIANTS[variant])
    rd = s.readiness()
    assert rd["ready"], h.failing_checks(rd)


@pytest.mark.parametrize("variant", ["normal", "holiday"])
def test_per_slot_15min_in_15min_store(variant):
    s = base_session(variant, slot=15)
    commit_kind(s, "forecast", HERE / "per_slot_headcount" / f"forecast_15min_{variant}.csv")
    assert slot_map(s) == bd.truth_15(bd.VARIANTS[variant])


@spec
def test_per_slot_15min_into_30min_store_takes_peak():
    """Spec 1b: rows finer than the store slot are aggregated to the slot by MAX headcount."""
    s = base_session("normal", slot=30)
    commit_kind(s, "forecast", HERE / "per_slot_headcount" / "forecast_15min_normal.csv")
    want: ref.SlotMap = {}
    for (rid, d, st), hc in bd.truth_15(bd.VARIANTS["normal"]).items():
        k = (rid, d, st - st % 30)
        want[k] = max(want.get(k, 0), hc)
    assert slot_map(s) == want


@pytest.mark.parametrize("variant", ["normal", "holiday"])
def test_solve_per_slot_30min(variant, record_property):
    s = base_session(variant)
    commit_kind(s, "forecast", HERE / "per_slot_headcount" / f"forecast_30min_{variant}.csv")
    out = h.summarize(s.solve())
    record_property("solve", out)
    print(variant, out)
    assert out["validator_passed"], out
    if variant == "normal":
        assert out["coverage_pct"] >= 80, out


# --------------------------------------------------------------------------- #
# 2. windowed_roles
# --------------------------------------------------------------------------- #
def _plan_rows(path: Path) -> list[dict]:
    import csv
    out = []
    for row in csv.DictReader(path.open()):
        out.append({"role": row["Role"], "days": row.get("Days") or row.get("Day"), "headcount": int(row["Headcount"]),
                    "start": h.imports.parse_time(row["Start"]), "end": h.imports.parse_time(row["End"])})
    return out


def test_windowed_per_day_imports_exactly():
    s = base_session("normal")
    r = commit_kind(s, "forecast", HERE / "windowed_roles" / "staffing_plan_per_day.csv")
    assert r.preview["unmapped_required"] == [] and not [w for w in r.warnings if "skipped" in w]
    assert slot_map(s) == ref.windows_to_slots(_plan_rows(HERE / "windowed_roles" / "staffing_plan_ranges.csv"), 30)
    assert s.readiness()["ready"]
    out = h.summarize(s.solve())
    print("windowed", out)
    assert out["validator_passed"], out


def test_windowed_day_ranges_today():
    """Today: `Days` maps to day, but 'Mon-Thu' / 'Daily' / 'Tue/Thu/Sat' can't be read -> rows skipped."""
    s = base_session("normal")
    r = commit_kind(s, "forecast", HERE / "windowed_roles" / "staffing_plan_ranges.csv")
    assert r.preview["proposed_mapping"]["Days"] == "day"
    skipped = [w for w in r.warnings if "skipped" in w]
    assert len(skipped) == 17 and s.config()["demand"] == []


@spec
def test_windowed_day_ranges_expand():
    s = base_session("normal")
    commit_kind(s, "forecast", HERE / "windowed_roles" / "staffing_plan_ranges.csv")
    assert slot_map(s) == ref.windows_to_slots(_plan_rows(HERE / "windowed_roles" / "staffing_plan_ranges.csv"), 30)


def test_second_forecast_import_replaces_all_corporate_demand_today():
    s = base_session("normal")
    commit_kind(s, "forecast", HERE / "windowed_roles" / "staffing_plan_per_day.csv")
    commit_kind(s, "forecast", HERE / "windowed_roles" / "truck_override.csv")
    assert {k[0] for k in slot_map(s)} == {"truck_unload"}


@spec
def test_forecast_import_replaces_only_its_role_days():
    """Spec 0: a demand import replaces corporate demand only for the (role, day) pairs it contains."""
    s = base_session("normal")
    commit_kind(s, "forecast", HERE / "windowed_roles" / "staffing_plan_per_day.csv")
    commit_kind(s, "forecast", HERE / "windowed_roles" / "truck_override.csv")
    want = {k: v for k, v in ref.windows_to_slots(_plan_rows(HERE / "windowed_roles" / "staffing_plan_ranges.csv"), 30).items()
            if not (k[0] == "truck_unload" and k[1] in (1, 3, 5))}
    want.update(ref.windows_to_slots(_plan_rows(HERE / "windowed_roles" / "truck_override.csv"), 30))
    assert slot_map(s) == want


# --------------------------------------------------------------------------- #
# 3. dept_daily_hours
# --------------------------------------------------------------------------- #
def _dept_hours(variant: str) -> dict[tuple[str, int], Fraction]:
    import csv
    rows = list(csv.reader((HERE / "dept_daily_hours" / f"labor_hours_{variant}.csv").open()))
    out = {}
    for row in rows[1:]:
        if row[0] == "TOTAL":
            continue
        for d in range(7):
            out[(row[0], d)] = Fraction(row[1 + d])
    return out


def _model() -> list[dict]:
    import csv
    out = []
    for row in csv.DictReader((HERE / "dept_daily_hours" / "labor_model.csv").open()):
        out.append({"dept": row["Dept"], "role": row["Role"], "share": int(row["Share %"]),
                    "start": h.imports.parse_time(row["Window Start"]) if row["Window Start"] else None,
                    "end": h.imports.parse_time(row["Window End"]) if row["Window End"] else None})
    return out


@pytest.mark.parametrize("variant", ["normal", "holiday"])
def test_dept_hours_unsupported_today(variant):
    s = base_session(variant)
    r = s.import_file("forecast", HERE / "dept_daily_hours" / f"labor_hours_{variant}.csv")
    assert set(r.preview["unmapped_required"]) == {"role", "day", "start", "headcount"}
    assert r.commit_status == 422
    m = s.import_file("forecast", HERE / "dept_daily_hours" / "labor_model.csv")
    assert m.preview["proposed_mapping"]["Window Start"] == "day"  # "dow" inside "window"


@spec
@pytest.mark.parametrize("variant", ["normal", "holiday", "promo", "light_january"])
def test_dept_hours_convert(variant):
    s = base_session(variant)
    cfg = s.config()
    cfg["budget"]["weekly_hours_cap"] = 0
    s.put(cfg)
    commit_kind(s, KIND_LABOR_MODEL, HERE / "dept_daily_hours" / "labor_model.csv")
    commit_kind(s, KIND_LABOR_HOURS, HERE / "dept_daily_hours" / f"labor_hours_{variant}.csv")
    want = ref.labor_hours_to_slots(_dept_hours(variant), _model(), open_hours(variant), 30)
    assert slot_map(s) == want
    assert s.config()["budget"]["weekly_hours_cap"] == VARIANTS[variant]["truth_headcount_hours"]


def test_dept_hours_reference_preserves_hours():
    """The spec's spreading keeps every department-day's hours (to the slot) and stays inside windows."""
    for variant in bd.VARIANTS:
        m = ref.labor_hours_to_slots(_dept_hours(variant), _model(), open_hours(variant), 30)
        got: dict[tuple[str, int], Fraction] = {}
        for (rid, d, _), hc in m.items():
            k = (bd.ROLE_DEPT[next(r for r in bd.ROLE_DEPT if ref.slug(r) == rid)], d)
            got[k] = got.get(k, Fraction(0)) + Fraction(hc * 30, 60)
        for k, hours in _dept_hours(variant).items():
            if k[1] in open_hours(variant):
                assert abs(got.get(k, 0) - hours) <= Fraction(1, 2), (variant, k, got.get(k), hours)
        assert not [k for k in m if k[0] == "truck_unload" and not 240 <= k[2] < 600]


# --------------------------------------------------------------------------- #
# 4. sales_driven
# --------------------------------------------------------------------------- #
def _sales(variant: str) -> list[dict]:
    import csv
    from datetime import date
    ws = date.fromisoformat(VARIANTS[variant]["week_start"])
    return [{"day": (date.fromisoformat(r["Date"]) - ws).days, "hour": h.imports.parse_time(r["Hour"]),
             "transactions": int(r["Transactions"]), "sales": r["Net Sales"], "online_orders": int(r["Online Orders"])}
            for r in csv.DictReader((HERE / "sales_driven" / f"sales_{variant}.csv").open())]


def test_sales_unsupported_today():
    s = base_session("normal")
    r = s.import_file("forecast", HERE / "sales_driven" / "sales_normal.csv")
    assert set(r.preview["unmapped_required"]) == {"role", "start", "headcount"} and r.commit_status == 422
    st = s.import_file("forecast", HERE / "sales_driven" / "labor_standards.csv")
    assert st.preview["proposed_mapping"]["Units per Staff Hour"] == "headcount" and st.commit_status == 422


@pytest.mark.parametrize("variant", ["normal", "holiday", "promo", "light_january"])
def test_spec_expectations_read_from_the_csvs(variant):
    """The xfail expectations, computed from the CSV files themselves, match the generator's truth."""
    v = bd.VARIANTS[variant]
    assert ref.sales_to_slots(_sales(variant), bd.STANDARDS, open_hours(variant), 30) == \
        ref.sales_to_slots(bd.sales_rows(v), bd.STANDARDS, open_hours(variant), 30)
    assert sum(_dept_hours(variant).values()) == Fraction(str(VARIANTS[variant]["truth_headcount_hours"]))
    assert ref.labor_hours_to_slots(_dept_hours(variant), _model(), open_hours(variant), 30)


@spec
@pytest.mark.parametrize("variant", ["normal", "holiday", "promo", "light_january"])
def test_sales_convert(variant):
    s = base_session(variant)
    commit_kind(s, KIND_STANDARDS, HERE / "sales_driven" / "labor_standards.csv")
    commit_kind(s, KIND_SALES, HERE / "sales_driven" / f"sales_{variant}.csv")
    assert slot_map(s) == ref.sales_to_slots(_sales(variant), bd.STANDARDS, open_hours(variant), 30)


# --------------------------------------------------------------------------- #
# 5. workload_units
# --------------------------------------------------------------------------- #
def test_workload_unsupported_today():
    s = base_session("normal")
    r = s.import_file("forecast", HERE / "workload_units" / "trucks_normal.csv")
    assert set(r.preview["unmapped_required"]) == {"role", "start", "headcount"} and r.commit_status == 422


def test_workload_forced_mapping_today():
    """If the leader forces Origin->role, Sched Arrival->start, Cases->headcount, the importer accepts a
    requirement for 2,880 people in a new role 'dc_0553'."""
    s = base_session("normal")
    r = commit_kind(s, "forecast", HERE / "workload_units" / "trucks_normal.csv",
                    {"Origin": "role", "Sched Arrival": "start", "Cases": "headcount"})
    hcs = {d["headcount"] for d in s.config()["demand"]}
    assert 2880 in hcs and any("dc_0553" in w for w in r.warnings)


@bug
def test_bug_absurd_headcount_flagged():
    s = base_session("normal")
    r = s.import_file("forecast", HERE / "workload_units" / "trucks_normal.csv",
                      {"Origin": "role", "Sched Arrival": "start", "Cases": "headcount"})
    assert r.commit_status != 200 or any("headcount" in w.lower() for w in r.warnings)


@spec
@pytest.mark.parametrize("variant", ["normal", "holiday"])
def test_workload_convert(variant):
    s = base_session(variant)
    commit_kind(s, KIND_STANDARDS, HERE / "workload_units" / "unload_standards.csv")
    commit_kind(s, KIND_WORKLOAD, HERE / "workload_units" / f"trucks_{variant}.csv")
    assert slot_map(s) == ref.workload_to_slots(bd.trucks(bd.VARIANTS[variant]), bd.UNLOAD, 30)


@spec
def test_full_week_from_mixed_styles():
    """standards + sales + windowed plan (softlines/hardlines) + trucks == the 30-min per-slot file."""
    s = base_session("normal")
    commit_kind(s, KIND_STANDARDS, HERE / "sales_driven" / "labor_standards.csv")
    commit_kind(s, KIND_STANDARDS, HERE / "workload_units" / "unload_standards.csv")
    commit_kind(s, KIND_SALES, HERE / "sales_driven" / "sales_normal.csv")
    commit_kind(s, "forecast", HERE / "windowed_roles" / "softlines_hardlines_plan.csv")
    commit_kind(s, KIND_WORKLOAD, HERE / "workload_units" / "trucks_normal.csv")
    assert slot_map(s) == bd.truth(bd.VARIANTS["normal"])
