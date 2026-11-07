"""Acceptance tests from briefs/WS3-laws.md."""
from shiftwright_contracts.models import Jurisdiction, LawRuleType as T

from shiftwright_laws import resolve


def types(pack):
    return {r.type for r in pack.rules}


def test_tx_austin_has_federal_ot_and_minor_rules():
    pack = resolve(Jurisdiction(state="TX", city="austin"))
    assert any(r.type == T.weekly_overtime and r.level == "federal" for r in pack.rules)
    assert T.minor_limits in types(pack)
    assert any(r.type == T.minor_prohibited_roles and "powered_industrial_truck" in r.params["role_tags"]
               for r in pack.rules)
    # Austin has a researched city file with no rules (Texas preempts city labor ordinances)
    assert pack.coverage == "full"
    assert not any(r.level == "city" for r in pack.rules)


def test_city_without_file_warns():
    pack = resolve(Jurisdiction(state="TX", city="round rock"))
    assert pack.coverage == "state_only"
    assert any("round rock" in w.lower() for w in pack.warnings)


def test_ca_has_daily_ot_meal_and_rest():
    pack = resolve(Jurisdiction(state="CA", city=None))
    assert {T.daily_overtime, T.meal_break, T.rest_break} <= types(pack)
    assert pack.coverage == "full"


def test_unknown_state_falls_back_to_federal():
    pack = resolve(Jurisdiction(state="ZZ"))
    assert pack.coverage == "federal_fallback"
    assert pack.warnings
    assert all(r.level == "federal" for r in pack.rules)
    assert T.weekly_overtime in types(pack)


def test_accepts_plain_strings_and_case():
    pack = resolve("ca", "Los Angeles")
    assert pack.jurisdiction.state == "CA"


def test_most_protective_minimum_wage_and_overtime_kept_once():
    pack = resolve(Jurisdiction(state="CA"))
    wages = [r for r in pack.rules if r.type == T.minimum_wage]
    assert len(wages) == 1 and wages[0].level == "state"
    weekly = [r for r in pack.rules if r.type == T.weekly_overtime]
    assert len(weekly) == 1


def test_minor_limits_stack_so_engine_enforces_both():
    # Federal 14-15 (18 h school week) is stricter than Texas (48 h); both kept, each with its citation.
    pack = resolve(Jurisdiction(state="TX"))
    minor = [r for r in pack.rules if r.type == T.minor_limits]
    assert {r.level for r in minor} == {"federal", "state"}


def test_low_confidence_excluded_by_default():
    pack = resolve(Jurisdiction(state="CA"))
    assert all(r.confidence != "low" for r in pack.rules)
