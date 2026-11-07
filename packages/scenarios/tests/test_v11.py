"""Contracts v1.1 in the generator and fixtures: Store.school_week and below_minimum_wage."""
import pytest
from shiftwright_contracts.models import LawRuleType
from shiftwright_laws import resolve

from shiftwright_scenarios import DIFFICULTIES, generate
from shiftwright_scenarios.fixtures import load_demo_scenario, load_demo_store, load_tiny_store
from shiftwright_scenarios.generator import WEEK_START

JURISDICTIONS = ["TX", "TX/austin", "CA", "CA/san_francisco", "WA/seattle", "IL/chicago", "NY/new_york"]
SIZES = ["S", "M", "L"]


def _floor(jur) -> float:
    pack = resolve(jur, on=WEEK_START)
    return max(float(r.params["dollars_per_hour"]) for r in pack.rules if r.type == LawRuleType.minimum_wage)


@pytest.mark.parametrize("jur", JURISDICTIONS)
@pytest.mark.parametrize("size", SIZES)
def test_wages_meet_minimum_except_trap(jur, size):
    for seed in (1, 2):
        for diff in DIFFICULTIES:
            sc = generate(seed, size, diff, jur)
            floor = _floor(sc.config.store.jurisdiction)
            low = {e.id for e in sc.config.employees if e.wage_per_hour < floor}
            trap = set(sc.expected["traps"].get("below_minimum_wage", []))
            assert low == trap, (seed, size, diff, jur)
            if diff == "legal_trap":
                assert len(trap) == 1
                assert sc.expected["traps"]["minimum_wage"]["dollars_per_hour"] == floor
            else:
                assert not trap


def test_wage_trap_is_schedulable():
    for jur in ("TX", "CA"):
        sc = generate(1, "M", "legal_trap", jur)
        (eid,) = sc.expected["traps"]["below_minimum_wage"]
        e = next(e for e in sc.config.employees if e.id == eid)
        assert e.age >= 18 and e.home_department_id != "leadership"
        assert e.wage_per_hour > 0


def test_committed_fixtures_meet_minimum_wage():
    for cfg in (load_tiny_store(), load_demo_store(), load_demo_scenario().config):
        floor = _floor(cfg.store.jurisdiction)
        assert all(e.wage_per_hour >= floor for e in cfg.employees)


def test_school_week():
    sc = generate(1, "S", "easy", "TX")
    assert sc.config.store.school_week is True
    assert sc.expected["school_week"] is True
    off = generate(1, "S", "easy", "TX", school_week=False)
    assert off.config.store.school_week is False and off.expected["school_week"] is False
    # Not part of the seed key: everything else is identical.
    assert off.config.employees == sc.config.employees
    assert generate(1, "S", "easy", "TX", school_week=None).config.store.school_week is None
    for cfg in (load_tiny_store(), load_demo_store(), load_demo_scenario().config):
        assert cfg.store.school_week is True  # Nov 9-15 2026: a normal school week in Austin
