"""State minor-hour limits: every researched state has school-week and non-school-week variants."""
import json
from pathlib import Path

import pytest
from shiftwright_contracts.models import Jurisdiction, LawRuleType as T

from shiftwright_laws import resolve

STATES_DIR = Path(__file__).resolve().parents[1] / "states"
MINOR_STATES = ["CA", "NY", "FL", "IL", "PA", "OH", "NC", "MI", "NJ", "WA", "AZ", "MA", "TN"]
# (state, age_min) bands whose law only limits school weeks (non-school weeks: federal floor only)
SCHOOL_WEEK_ONLY = {("FL", 16), ("OH", 16), ("NC", 16), ("TN", 16)}


def minor_rules(state):
    doc = json.loads((STATES_DIR / f"{state}.json").read_text())
    return [r for r in doc["rules"] if r["type"] == "minor_limits"]


@pytest.mark.parametrize("state", MINOR_STATES)
def test_each_age_band_has_both_school_week_variants(state):
    rules = minor_rules(state)
    assert rules, state
    bands = {(r["params"]["age_min"], r["params"]["age_max"]) for r in rules}
    for band in bands:
        variants = {r["params"]["school_week"] for r in rules
                    if (r["params"]["age_min"], r["params"]["age_max"]) == band}
        expected = {True} if (state, band[0]) in SCHOOL_WEEK_ONLY else {True, False}
        assert variants == expected, (state, band)
    for r in rules:
        assert r["confidence"] == "high" and r["citation"]["url"].startswith("http")


@pytest.mark.parametrize("state", MINOR_STATES)
def test_researched_states_drop_the_not_yet_researched_note(state):
    doc = json.loads((STATES_DIR / f"{state}.json").read_text())
    assert not any("minor-hour limits not yet researched" in n for n in doc["notes"])


def test_ny_16_17_school_week_is_28_hours():
    pack = resolve(Jurisdiction(state="NY"))
    rule = next(r for r in pack.rules if r.type == T.minor_limits and r.level == "state"
                and r.params["age_min"] == 16 and r.params["school_week"] is True)
    assert rule.params["max_hours_week"] == 28
    assert rule.params["max_hours_day"] == 4


# States researched where state law adds no hour limits beyond federal; they say so in notes.
NO_EXTRA_STATE_LIMITS = ["GA", "VA"]


@pytest.mark.parametrize("state", NO_EXTRA_STATE_LIMITS)
def test_states_without_extra_limits_say_so(state):
    doc = json.loads((STATES_DIR / f"{state}.json").read_text())
    assert any(n.startswith("Minors researched") for n in doc["notes"])
    assert not any("minor-hour limits not yet researched" in n for n in doc["notes"])


def test_mi_future_wage_not_in_force_early():
    from datetime import date
    wage = lambda on: next(r for r in resolve("MI", on=on).rules if r.type == T.minimum_wage)
    assert wage(date(2026, 11, 9)).params["dollars_per_hour"] == 13.73
    assert wage(date(2027, 1, 4)).params["dollars_per_hour"] == 15.0
