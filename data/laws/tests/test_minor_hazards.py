"""Federal hazardous-occupation rules for minors (29 CFR Part 570) mapped to ROLE_TAGS (PUNCHLIST D1)."""
import pytest
from shiftwright_contracts.models import ROLE_TAGS, LawRuleType as T

from shiftwright_laws import resolve

UNDER_18 = {  # tag -> section of the hazardous occupations order (all "minors between 16 and 18")
    "powered_industrial_truck": "570.58",
    "meat_slicer": "570.61",
    "bakery_machine": "570.62",
    "baler_compactor": "570.63",
    "motor_vehicle_driving": "570.52",
    "power_saw": "570.65",
}
UNDER_16 = {"cooking", "fryer", "ladder_scaffold", *UNDER_18}


def federal_role_rules(pack):
    return [r for r in pack.rules if r.type == T.minor_prohibited_roles and r.level == "federal"]


def banned(rules, tag, age):
    return [r for r in rules if tag in r.params["role_tags"]
            and (r.params.get("age_min") or 0) <= age < r.params["age_below"]]


@pytest.fixture(scope="module")
def chicago():
    return federal_role_rules(resolve("IL", "chicago"))


def test_tags_exist_in_contract(chicago):
    for r in chicago:
        assert set(r.params["role_tags"]) <= set(ROLE_TAGS), r.id


@pytest.mark.parametrize("tag,section", UNDER_18.items())
def test_hazardous_orders_bar_under_18(chicago, tag, section):
    hits = banned(chicago, tag, 17)
    assert hits, tag
    assert any(section in r.citation.url and r.params.get("age_min") is None for r in hits)
    assert not banned(chicago, tag, 18)


@pytest.mark.parametrize("tag", sorted(UNDER_16))
def test_14_15_bans(chicago, tag):
    assert banned(chicago, tag, 14) and banned(chicago, tag, 15)


@pytest.mark.parametrize("tag", ["cooking", "fryer", "ladder_scaffold"])
def test_kitchen_and_ladder_bans_stop_at_16(chicago, tag):
    assert not banned(chicago, tag, 16)


def test_fryer_rule_cites_the_fryer_exception(chicago):
    rule = next(r for r in chicago if r.id == "US.minor_prohibited_roles.7")
    assert rule.params["role_tags"] == ["cooking", "fryer"]
    assert (rule.params["age_min"], rule.params["age_below"]) == (14, 16)
    assert "570.34(c)" in rule.citation.title
    assert "automatically lowers the baskets" in rule.citation.excerpt
