"""Food-service scenarios (generate(..., sector="food")) and the demo restaurant fixture."""
import pytest
from shiftwright_contracts.models import ROLE_TAGS, EventKind, LawRuleType, Sector, StoreConfig
from shiftwright_laws import resolve

from shiftwright_scenarios import DIFFICULTIES, FIXTURES_DIR, Scenario, generate, load_demo_scenario, load_demo_store
from shiftwright_scenarios.food import ROLES, WEEK_START, build_demo_restaurant, hourly_demand

JURS = ["IL/chicago", "TX", "CA", "WA/seattle"]


def _gen(seed=1, size="M", diff="normal", jur="IL/chicago"):
    return generate(seed, size, diff, jur, sector="food")


def _floors(jur):
    pack = resolve(jur, on=WEEK_START)
    full = max(float(r.params["dollars_per_hour"]) for r in pack.rules if r.type == LawRuleType.minimum_wage)
    tipped = [float(r.params["cash_wage_per_hour"]) for r in pack.rules if r.type == LawRuleType.tipped_minimum_wage]
    return full, (max(tipped) if tipped else full)


def test_deterministic_and_distinct():
    assert _gen().model_dump_json() == _gen().model_dump_json()
    assert _gen(1).model_dump_json() != _gen(2).model_dump_json()
    assert generate(1, "M", "normal", "IL/chicago").config.store.sector is None  # retail path unchanged


@pytest.mark.parametrize("size", ["S", "M", "L"])
@pytest.mark.parametrize("diff", DIFFICULTIES)
def test_outputs_validate(size, diff):
    sc = _gen(1, size, diff)
    StoreConfig.model_validate_json(sc.config.model_dump_json())
    Scenario.model_validate_json(sc.model_dump_json())
    cfg = sc.config
    assert cfg.store.sector == Sector.food and cfg.store.max_shifts_per_day == 2
    assert len(sc.history) == 8 and sc.narrative
    assert {d.role_id for d in cfg.demand} <= {r for e in cfg.employees for r in e.trained_role_ids}
    assert all(t in ROLE_TAGS for tags in cfg.role_tags.values() for t in tags)
    assert sum(e.age < 18 for e in cfg.employees) >= 2
    assert sc.expected["infeasible"] == (diff == "infeasible")


def test_roles_tags_and_tipping():
    cfg = _gen().config
    roles = {r.id: r for r in cfg.roles}
    assert set(roles) == set(ROLES)
    assert {r for r, x in roles.items() if x.tipped} == {"server", "bartender"}
    assert cfg.role_tags == {"bartender": ["alcohol_service"], "line_cook": ["cooking", "fryer"],
                             "prep_cook": ["meat_slicer"]}
    for e in cfg.employees:
        tipped_trained = any(roles[r].tipped for r in e.trained_role_ids)
        assert (e.tipped_wage_per_hour is not None) == tipped_trained
        if e.tipped_wage_per_hour is not None:
            assert e.tipped_wage_per_hour <= e.wage_per_hour
        if e.age < 18:  # store policy outside legal_trap / the demo: no minors at the bar, line or slicer
            assert not {"bartender", "line_cook", "prep_cook", "manager_on_duty"} & set(e.trained_role_ids)


@pytest.mark.parametrize("jur", JURS)
def test_wages_and_tipped_wages_meet_law_floors(jur):
    for size in ("S", "M", "L"):
        for diff in DIFFICULTIES:
            cfg = _gen(2, size, diff, jur).config
            full, tipped = _floors(cfg.store.jurisdiction)
            assert all(e.wage_per_hour >= full for e in cfg.employees)
            assert all(e.tipped_wage_per_hour >= tipped for e in cfg.employees if e.tipped_wage_per_hour is not None)


def test_peaks_and_private_event():
    lunch = hourly_demand("server", 0, 1.0, event=False)
    assert lunch[12][0] > lunch[15][0] < lunch[18][0]          # lunch and dinner peaks
    sat = hourly_demand("server", 5, 1.0, event=False)
    assert sat[18][0] > lunch[18][0]                            # Saturday heavier
    cfg = _gen().config
    (ev,) = cfg.events
    assert ev.kind == EventKind.private_event and ev.label and ev.day == 3
    evd = [d for d in cfg.demand if d.event_id == ev.id]
    assert evd and {d.role_id for d in evd} == {"server", "bartender", "line_cook"}
    by_rd: dict = {}
    for d in cfg.demand:  # same (role, day) never overlaps
        for o in by_rd.get((d.role_id, d.day), []):
            assert d.end <= o.start or o.end <= d.start
        by_rd.setdefault((d.role_id, d.day), []).append(d)


def test_legal_trap_minors():
    sc = _gen(1, "M", "legal_trap")
    emps = {e.id: e for e in sc.config.employees}
    (fry,) = sc.expected["traps"]["minor_fryer_trained"]
    assert emps[fry].age == 15 and "line_cook" in emps[fry].trained_role_ids
    for eid in sc.expected["traps"]["minor_alcohol_trained"]:
        assert emps[eid].age < 18 and "bartender" in emps[eid].trained_role_ids


def test_narrative_budget_exact():
    for diff in DIFFICULTIES:
        sc = _gen(1, "M", diff)
        cap = sc.config.budget.weekly_hours_cap
        if any(f["kind"] == "budget_hours_cap" for f in sc.expected["narrative_facts"]):
            assert f"{cap:,.0f} hours" in sc.narrative


# --------------------------------------------------------------------------- #
# demo restaurant
# --------------------------------------------------------------------------- #
def test_demo_restaurant_fixture_matches_builder():
    built = build_demo_restaurant()
    assert (FIXTURES_DIR / "demo_scenario_restaurant.json").read_text() == built.model_dump_json(indent=2) + "\n"
    assert (FIXTURES_DIR / "demo_store_restaurant.json").read_text() == built.config.model_dump_json(indent=2) + "\n"
    assert load_demo_store("restaurant") == built.config
    assert load_demo_scenario("restaurant").config == built.config


def test_demo_restaurant_story():
    sc = load_demo_scenario("restaurant")
    cfg = sc.config
    s = cfg.store
    assert s.name == "Harbor Grill #12, Chicago IL"
    assert (s.jurisdiction.state, s.jurisdiction.city) == ("IL", "chicago")
    assert s.sector == Sector.food and s.max_shifts_per_day == 2 and s.school_week is True
    assert s.employer_employee_count and (s.week_start - s.schedule_posted_on).days == 14
    emps = {e.id: e for e in cfg.employees}
    minor = emps[sc.expected["demo"]["minor_fryer_id"]]
    assert minor.age == 15 and "line_cook" in minor.trained_role_ids
    assert "fryer" in cfg.role_tags["line_cook"]
    assert [c.employee_id for c in sc.callout_events] == sc.expected["demo"]["callout_employee_ids"]
    assert all(c.day == 5 and c.reported_at == 930 for c in sc.callout_events)
    assert "14 days ahead" in sc.narrative and f"{cfg.budget.weekly_hours_cap:,.0f} hours" in sc.narrative
    pack_ids = {r.id for r in resolve(s.jurisdiction, on=s.week_start).rules}
    assert all(n["law_rule_id"] in pack_ids for n in sc.expected["law_context"])
