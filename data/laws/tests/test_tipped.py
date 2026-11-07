"""Tipped minimum wage resolution (SEMANTICS #20)."""
from datetime import date

from shiftwright_contracts.models import Jurisdiction, LawRuleType as T

from shiftwright_laws import resolve

ON = date(2026, 11, 9)


def tipped(state, city=None):
    rules = [r for r in resolve(Jurisdiction(state=state, city=city), on=ON).rules
             if r.type == T.tipped_minimum_wage]
    assert len(rules) <= 1
    return rules[0] if rules else None


def test_chicago_tipped_wage_is_city_rate():
    r = tipped("IL", "chicago")
    assert r.id == "IL.chicago.tipped_minimum_wage.1" and r.params["cash_wage_per_hour"] == 12.96


def test_illinois_and_texas():
    assert tipped("IL").params["cash_wage_per_hour"] == 9.0
    assert tipped("TX").params["cash_wage_per_hour"] == 2.13
    assert tipped("TX", "austin").level == "state"


def test_no_tip_credit_states_get_no_rule():
    # The federal $2.13 must not leak into states whose own minimum wage has no tip credit.
    assert tipped("CA") is None and tipped("CA", "san francisco") is None
    assert tipped("WA") is None and tipped("WA", "seattle") is None


def test_unknown_state_falls_back_to_federal():
    assert tipped("ZZ").level == "federal"
