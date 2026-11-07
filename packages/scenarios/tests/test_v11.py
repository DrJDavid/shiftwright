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
@pytest.mark.parametrize("sector", ["retail", "food"])
def test_nobody_below_minimum_wage(jur, size, sector):
    """No generated employee is ever below the resolved minimum (the below_minimum_wage trap is gone)."""
    for seed in (1, 2):
        for diff in DIFFICULTIES:
            sc = generate(seed, size, diff, jur, sector=sector)
            floor = _floor(sc.config.store.jurisdiction)
            low = [(e.id, e.wage_per_hour) for e in sc.config.employees if e.wage_per_hour < floor]
            assert not low, (seed, size, diff, jur, sector, floor, low)
            assert "below_minimum_wage" not in sc.expected["traps"]


def test_ca_legal_trap_allows_split_shifts():
    for size in SIZES:
        sc = generate(1, size, "legal_trap", "CA")
        assert sc.config.store.max_shifts_per_day == 2
        assert sc.expected["infeasible"] is False
    assert generate(1, "S", "legal_trap", "TX").config.store.max_shifts_per_day == 1
    assert generate(1, "S", "normal", "CA").config.store.max_shifts_per_day == 1


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


def test_narrative_hours_cap_is_exact():
    """The narrative must state the configured cap exactly (1,393.5 was once rounded to 1,394)."""
    for seed in (1, 2, 3):
        for size in SIZES:
            for diff in DIFFICULTIES:
                sc = generate(seed, size, diff, "TX")
                if not any(f["kind"] == "budget_hours_cap" for f in sc.expected["narrative_facts"]):
                    continue
                cap = sc.config.budget.weekly_hours_cap
                text = f"{cap:,.0f}" if cap == int(cap) else f"{cap:,.1f}"
                assert f"{text} hours" in sc.narrative, (seed, size, diff, cap)
