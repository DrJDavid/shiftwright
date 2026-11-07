"""Acceptance tests for generate() (WS4 brief, deliverable 2)."""
import importlib

import pytest
from shiftwright_contracts.models import Schedule, StoreConfig

from shiftwright_scenarios import DIFFICULTIES, Scenario, generate

SIZES = ["S", "M", "L"]
CASES = [(seed, size, diff) for seed in (1, 2) for size in SIZES for diff in DIFFICULTIES]


@pytest.fixture(scope="module")
def scenarios() -> dict:
    return {c: generate(c[0], c[1], c[2], "TX") for c in CASES}


def test_same_seed_byte_identical():
    a = generate(7, "M", "tight", "TX").model_dump_json()
    b = generate(7, "M", "tight", "TX").model_dump_json()
    assert a == b


def test_different_seeds_differ():
    assert generate(1, "S", "easy", "TX").model_dump_json() != generate(2, "S", "easy", "TX").model_dump_json()


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[1]}-{c[2]}-{c[0]}")
def test_outputs_validate(scenarios, case):
    sc = scenarios[case]
    assert isinstance(sc, Scenario)
    StoreConfig.model_validate_json(sc.config.model_dump_json())
    Scenario.model_validate_json(sc.model_dump_json())
    assert len(sc.history) == 8
    assert sc.narrative
    assert sc.expected["difficulty"] == case[2]


def test_staff_counts_near_size(scenarios):
    for (seed, size, diff), sc in scenarios.items():
        n = len(sc.config.employees)
        lo, hi = {"S": (20, 32), "M": (50, 72), "L": (100, 140)}[size]
        assert lo <= n <= hi, (size, diff, n)


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[1]}-{c[2]}-{c[0]}")
def test_referential_integrity_and_grid(scenarios, case):
    cfg = scenarios[case].config
    slot = cfg.store.slot_minutes
    role_ids = {r.id for r in cfg.roles}
    dept_ids = {d.id for d in cfg.departments}
    emp_ids = [e.id for e in cfg.employees]
    assert len(set(emp_ids)) == len(emp_ids)
    assert len({e.name for e in cfg.employees}) == len(emp_ids)
    for e in cfg.employees:
        assert e.home_department_id in dept_ids
        assert e.trained_role_ids and set(e.trained_role_ids) <= role_ids
        for a in e.availability:
            assert a.start % slot == 0 and a.end % slot == 0 and a.start < a.end
            assert (a.weekday is None) != (a.on_date is None)
    hours = {h.day: h for h in cfg.store.hours}
    spans: dict = {}
    for d in cfg.demand:
        assert d.role_id in role_ids and d.headcount >= 1
        assert d.start % slot == 0 and d.end % slot == 0 and d.start < d.end
        h = hours[d.day]
        assert h.open - cfg.store.pre_open_minutes <= d.start
        assert d.end <= h.close + cfg.store.post_close_minutes
        spans.setdefault((d.role_id, d.day), []).append((d.start, d.end))
    for s in spans.values():
        s.sort()
        assert all(a[1] <= b[0] for a, b in zip(s, s[1:]))
    for c in cfg.constraints:
        if c.strength.value == "soft":
            assert c.weight_dollars > 0
        assert c.source.value != "law"
        for eid in c.params.get("employee_ids", []) + ([c.params["employee_id"]] if "employee_id" in c.params else []):
            assert eid in emp_ids


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[1]}-{c[2]}-{c[0]}")
def test_every_demanded_role_has_trained_employee(scenarios, case):
    cfg = scenarios[case].config
    trained = {r for e in cfg.employees for r in e.trained_role_ids}
    assert {d.role_id for d in cfg.demand} <= trained


def test_mix_roughly_matches_brief(scenarios):
    cfg = scenarios[(1, "L", "easy")].config
    n = len(cfg.employees)
    minors = sum(e.age < 18 for e in cfg.employees)
    ft = sum(e.status.value == "full_time" for e in cfg.employees)
    assert 0.04 * n <= minors <= 0.12 * n
    assert 0.2 * n <= ft <= 0.4 * n
    for e in cfg.employees:
        lo, hi = (24, 30) if "leader_on_duty" in e.trained_role_ids and e.home_department_id == "leadership" else (15, 22)
        assert lo <= e.wage_per_hour <= hi
        if e.age < 18 and "pit_operator" in e.trained_role_ids:
            pytest.fail("minor PIT training only in legal_trap / demo")


def test_budget_ratio_by_difficulty(scenarios):
    for (seed, size, diff), sc in scenarios.items():
        need = sum(d.headcount * (d.end - d.start) / 60 for d in sc.config.demand)
        ratio = need / sc.config.budget.weekly_hours_cap
        assert sc.expected["required_hours"] == pytest.approx(need)
        if diff == "easy":
            assert ratio < 0.9
        elif diff == "tight":
            assert 1.08 <= ratio <= 1.14  # budget ~90% of need
        else:
            assert 1.02 <= ratio <= 1.08  # need ~105% of cap


def test_infeasible_expected(scenarios):
    for (seed, size, diff), sc in scenarios.items():
        assert sc.expected["infeasible"] is (diff == "infeasible")
        if diff == "infeasible":
            ids = sc.expected["conflicting_ids"]
            assert "c_lod_always" in ids and len(ids) >= 2
            lod_trained = [e for e in sc.config.employees if "leader_on_duty" in e.trained_role_ids]
            assert lod_trained  # still >=1 trained


def test_legal_trap_has_traps(scenarios):
    sc = scenarios[(1, "M", "legal_trap")]
    traps = sc.expected["traps"]
    emps = {e.id: e for e in sc.config.employees}
    assert traps["minor_pit_trained"]
    for eid in traps["minor_pit_trained"]:
        assert emps[eid].age < 18 and "pit_operator" in emps[eid].trained_role_ids
    assert traps["clopen_prone"]


def test_messy_narrative_has_contradiction(scenarios):
    sc = scenarios[(1, "M", "messy")]
    assert sc.expected["narrative_contradictions"]
    assert sc.expected["narrative_omissions"]
    clean = scenarios[(1, "M", "normal")]
    assert not clean.expected["narrative_contradictions"]
    assert clean.expected["narrative_facts"]


@pytest.mark.parametrize("case", [(1, "M", "normal"), (2, "S", "legal_trap")], ids=str)
def test_history_well_formed(scenarios, case):
    sc = scenarios[case]
    cfg = sc.config
    emps = {e.id: e for e in cfg.employees}
    min_age = {r.id: r.min_age for r in cfg.roles}
    assert [h.week_start for h in sc.history] == sorted(h.week_start for h in sc.history)
    assert all(h.week_start < cfg.store.week_start for h in sc.history)
    for wk in sc.history:
        assert isinstance(wk, Schedule) and wk.produced_by == "history"
        per_emp_day: dict = {}
        for s in wk.shifts:
            e = emps[s.employee_id]
            assert sum(seg.end - seg.start for seg in s.segments) == s.end - s.start
            for seg in s.segments:
                assert seg.role_id in e.trained_role_ids
                assert e.age >= min_age[seg.role_id]
            per_emp_day.setdefault((s.employee_id, s.day), []).append(s)
        assert all(len(v) == 1 for v in per_emp_day.values())


def test_callouts_reference_employees(scenarios):
    for sc in scenarios.values():
        ids = {e.id for e in sc.config.employees}
        assert sc.callout_events
        assert all(c.employee_id in ids for c in sc.callout_events)


def test_easy_engine_coverage():
    """Brief: easy scenarios reach >=98% coverage with the engine (skips until WS1 lands)."""
    engine = importlib.import_module("shiftwright_engine")
    solve_week = getattr(engine, "solve_week", None)
    if solve_week is None:
        pytest.skip("shiftwright_engine.solve_week not available yet")
    sc = generate(1, "S", "easy", "TX")
    sched = solve_week(sc.config, time_limit_s=30)
    assert sched.metrics is not None
    cov = sched.metrics.coverage_pct
    cov = cov * 100 if cov <= 1.0 else cov  # contract doesn't fix the unit (0-1 vs 0-100)
    assert cov >= 98.0
