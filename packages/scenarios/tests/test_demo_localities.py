"""Demo store variants per locality (Austin, Chicago, Seattle, San Francisco)."""
from datetime import timedelta

import pytest
from shiftwright_contracts.models import LawRuleType
from shiftwright_laws import resolve

from shiftwright_scenarios import DEMO_LOCALITIES, FIXTURES_DIR, load_demo_scenario, load_demo_store
from shiftwright_scenarios.demo import LOCALITIES, build_demo_scenario, fixture_names

EXPECTED = {
    "austin": ("Store #0417, Austin TX", "TX", "austin"),
    "chicago": ("Store #1123, Chicago IL", "IL", "chicago"),
    "seattle": ("Store #2231, Seattle WA", "WA", "seattle"),
    "sf": ("Store #3305, San Francisco CA", "CA", "san francisco"),
}


@pytest.fixture(scope="module")
def scenarios():
    return {loc: load_demo_scenario(loc) for loc in DEMO_LOCALITIES}


def test_locality_lists_agree():
    assert set(DEMO_LOCALITIES) == set(LOCALITIES) == set(EXPECTED)


@pytest.mark.parametrize("loc", DEMO_LOCALITIES)
def test_committed_fixtures_match_builder(loc):
    built = build_demo_scenario(loc)
    store_f, scen_f = fixture_names(loc)
    assert (FIXTURES_DIR / scen_f).read_text() == built.model_dump_json(indent=2) + "\n"
    assert (FIXTURES_DIR / store_f).read_text() == built.config.model_dump_json(indent=2) + "\n"
    assert load_demo_store(loc) == built.config


def test_default_is_austin():
    assert fixture_names() == ("demo_store.json", "demo_scenario.json")
    assert load_demo_store() == load_demo_store("austin")
    with pytest.raises(ValueError):
        load_demo_store("houston")


@pytest.mark.parametrize("loc", DEMO_LOCALITIES)
def test_store_fields(scenarios, loc):
    cfg = scenarios[loc].config
    name, state, city = EXPECTED[loc]
    s = cfg.store
    assert s.name == name
    assert (s.jurisdiction.state, s.jurisdiction.city) == (state, city)
    assert s.school_week is True
    assert s.employer_employee_count and s.employer_employee_count > 1000
    assert s.schedule_posted_on == s.week_start - timedelta(days=14)


@pytest.mark.parametrize("loc", DEMO_LOCALITIES)
def test_wages_meet_resolved_minimum(scenarios, loc):
    cfg = scenarios[loc].config
    pack = resolve(cfg.store.jurisdiction, on=cfg.store.week_start)
    floor = max(float(r.params["dollars_per_hour"]) for r in pack.rules if r.type == LawRuleType.minimum_wage)
    assert all(e.wage_per_hour >= floor for e in cfg.employees)


def test_same_staff_ids_and_callouts(scenarios):
    austin = scenarios["austin"]
    base_ids = [e.id for e in austin.config.employees]
    for loc, sc in scenarios.items():
        ids = [e.id for e in sc.config.employees]
        assert ids[: len(base_ids)] == base_ids
        assert ids[len(base_ids):] == sc.expected["new_hire_ids"]
        assert [c.employee_id for c in sc.callout_events] == ["e034", "e052", "e053"]
        assert [h.shifts for h in sc.history] == [h.shifts for h in austin.history]
        a = {e.id: e for e in austin.config.employees}
        for e in sc.config.employees[: len(base_ids)]:
            assert (e.name, e.age, e.trained_role_ids) == (a[e.id].name, a[e.id].age, a[e.id].trained_role_ids)


@pytest.mark.parametrize("loc", DEMO_LOCALITIES)
def test_narrative_matches_config_and_law_pack(scenarios, loc):
    sc = scenarios[loc]
    cap = sc.config.budget.weekly_hours_cap
    assert cap == int(cap) and f"{int(cap):,} hours" in sc.narrative
    pack_ids = {r.id for r in resolve(sc.config.store.jurisdiction, on=sc.config.store.week_start).rules}
    notes = sc.expected["law_context"]
    assert all(n["law_rule_id"] in pack_ids for n in notes)
    if loc == "austin":
        assert notes == []
    else:
        assert notes and "minimum wage" in sc.narrative
    if loc in ("chicago", "seattle", "sf"):
        assert "14 days ahead" in sc.narrative  # predictive_scheduling.notice_days in each city's pack
