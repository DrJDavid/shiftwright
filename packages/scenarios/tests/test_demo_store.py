"""Acceptance tests for the demo store (WS4 deliverable 3, SPEC §7)."""
import pytest

from shiftwright_scenarios import FIXTURES_DIR, load_demo_scenario, load_demo_store
from shiftwright_scenarios.demo import apply_demo_phones, build_demo_scenario


@pytest.fixture(scope="module")
def sc():
    return load_demo_scenario()


def test_committed_fixtures_match_builder(sc):
    built = build_demo_scenario()
    assert (FIXTURES_DIR / "demo_scenario.json").read_text() == built.model_dump_json(indent=2) + "\n"
    assert (FIXTURES_DIR / "demo_store.json").read_text() == built.config.model_dump_json(indent=2) + "\n"


def test_store_identity(sc):
    cfg = load_demo_store()
    assert cfg == sc.config
    assert cfg.store.name == "Store #0417, Austin TX"
    assert cfg.store.jurisdiction.state == "TX" and cfg.store.jurisdiction.city == "austin"
    assert cfg.store.slot_minutes == 30
    assert 50 <= len(cfg.employees) <= 72


def test_jordan_casey_not_together(sc):
    emps = {e.id: e for e in sc.config.employees}
    d = sc.expected["demo"]
    assert emps[d["jordan_id"]].name.startswith("Jordan ")
    assert emps[d["casey_id"]].name.startswith("Casey ")
    nt = [c for c in sc.config.constraints if c.kind.value == "not_together"]
    assert any(set(c.params["employee_ids"]) == {d["jordan_id"], d["casey_id"]} for c in nt)
    # history never puts them on together (insights should mine the separation)
    for wk in sc.history:
        by_day: dict = {}
        for s in wk.shifts:
            if s.employee_id in (d["jordan_id"], d["casey_id"]):
                by_day.setdefault(s.day, []).append(s)
        for shifts in by_day.values():
            if len(shifts) == 2:
                a, b = shifts
                assert a.end <= b.start or b.end <= a.start


def test_minor_flagged_pit_trained(sc):
    emps = {e.id: e for e in sc.config.employees}
    e = emps[sc.expected["demo"]["minor_pit_id"]]
    assert e.age == 17 and "pit_operator" in e.trained_role_ids
    assert [x.id for x in sc.config.employees if x.age < 18 and "pit_operator" in x.trained_role_ids] == [e.id]


def test_saturday_truck(sc):
    ev = [e for e in sc.config.events if e.day == 5 and e.kind.value == "truck"]
    assert len(ev) == 1 and (ev[0].start, ev[0].end) == (240, 600)
    roles = {d.role_id for d in sc.config.demand if d.event_id == ev[0].id}
    assert {"truck_unload", "backroom", "pit_operator"} <= roles


def _cashiers_at(sched, day, hour):
    t = hour * 60
    return sum(1 for s in sched.shifts if s.day == day
               for g in s.segments if g.role_id == "cashier" and g.start <= t < g.end)


def test_cashier_after_5pm_pattern(sc):
    assert len(sc.history) == 8
    for wk in sc.history:
        for day in range(7):
            for hour in range(17, 22):
                assert _cashiers_at(wk, day, hour) >= 2, (wk.week_start, day, hour)
    # ...while the corporate forecast asks for only 1 late on weekdays, so the pattern adds information
    late = [d for d in sc.config.demand if d.role_id == "cashier" and d.day < 4 and d.start >= 19 * 60]
    assert late and all(d.headcount == 1 for d in late)


def test_saturday_callouts(sc):
    ids = {e.id for e in sc.config.employees}
    assert len(sc.callout_events) == 3
    assert all(c.day == 5 and c.reported_at == 364 and c.employee_id in ids for c in sc.callout_events)


def test_demo_phones(monkeypatch, sc):
    ids = sc.expected["demo"]["demo_phone_employee_ids"]
    assert len(ids) == 2
    monkeypatch.delenv("DEMO_PHONE_1", raising=False)
    monkeypatch.delenv("DEMO_PHONE_2", raising=False)
    assert apply_demo_phones(sc.config) == sc.config
    monkeypatch.setenv("DEMO_PHONE_1", "+15550001111")
    monkeypatch.setenv("DEMO_PHONE_2", "+15550002222")
    cfg = apply_demo_phones(sc.config)
    phones = {e.id: e.phone for e in cfg.employees}
    assert phones[ids[0]] == "+15550001111" and phones[ids[1]] == "+15550002222"
    assert sc.config.employees != cfg.employees  # original not mutated in place... returns a copy
    emps = {e.id: e for e in sc.config.employees}
    for eid in ids:  # best call-in odds in the store
        a = emps[eid].attendance
        assert a.callins_offered_90d >= 8 and a.callins_accepted_90d / a.callins_offered_90d >= 0.85


def test_every_demanded_role_trained_and_budget(sc):
    cfg = sc.config
    trained = {r for e in cfg.employees for r in e.trained_role_ids}
    assert {d.role_id for d in cfg.demand} <= trained
    need = sum(d.headcount * (d.end - d.start) / 60 for d in cfg.demand)
    assert 1.02 <= need / cfg.budget.weekly_hours_cap <= 1.08
