"""Predictive-scheduling premium params for the demo cities round-trip through resolve() (SEMANTICS #17)."""
from shiftwright_contracts.models import Jurisdiction, LawRuleType as T

from shiftwright_laws import resolve


def ps_rule(state, city):
    pack = resolve(Jurisdiction(state=state, city=city))
    rules = [r for r in pack.rules if r.type == T.predictive_scheduling]
    assert len(rules) == 1, rules
    return rules[0]


def test_chicago_predictability_pay_params():
    r = ps_rule("IL", "chicago")
    p = r.params
    assert r.id == "IL.chicago.predictive_scheduling.1" and r.confidence == "high"
    assert p["notice_days"] == 14
    assert p["applies_if_employees_over"] == 99 and p["min_covered_employees"] == 50
    assert p["premium_basis"] == "regular_rate"
    assert p["change_premium_hours"] == 1 and p["change_premium_hours_under_24h"] == 1
    assert p["moved_premium_hours"] == 1 and p["reduced_premium_hours"] == 1
    assert p["reduced_hours_fraction"] == 0.5 and p["reduced_fraction_notice_hours"] == 24
    assert p["voluntary_additional_hours_exempt"] is True
    assert p["consent_must_be_written"] is True and p["text_message_counts_as_written"] is True
    assert p["exemption_requires_group_message"] is False
    assert len(p["exemption_note"].split()) <= 40
    assert "6-110-050" in r.citation.title


def test_seattle_secure_scheduling_params():
    r = ps_rule("WA", "seattle")
    p = r.params
    assert r.id == "WA.seattle.predictive_scheduling.1" and r.confidence == "high"
    assert p["notice_days"] == 14 and p["applies_if_employees_over"] == 499
    assert p["premium_basis"] == "scheduled_rate"
    assert p["change_premium_hours"] == 1 and p["moved_premium_hours"] == 1
    assert p["prorate_added_under_1h"] is True and p["grace_minutes"] == 15
    assert p["reduced_hours_fraction"] == 0.5 and p["reduced_fraction_notice_hours"] is None
    assert p["voluntary_additional_hours_exempt"] is True and p["consent_must_be_written"] is True
    assert p["exemption_requires_group_message"] is True and p["exemption_min_recipients"] == 2
    assert p["exemption_only_for_absent_coworker_hours"] is True
    assert len(p["exemption_message_must_state"]) == 3
    assert len(p["exemption_note"].split()) <= 40


import pytest

ALL_PS = [("IL", "chicago"), ("WA", "seattle"), ("NY", "new york"), ("CA", "san francisco"),
          ("CA", "los angeles"), ("PA", "philadelphia"), ("OR", None), ("CA", "berkeley"),
          ("CA", "emeryville"), ("IL", "evanston")]


@pytest.mark.parametrize("state,city", ALL_PS)
def test_every_fair_workweek_rule_has_premium_and_exemption_keys(state, city):
    p = ps_rule(state, city).params
    assert {"notice_days", "premium_basis", "change_premium_hours", "applies_if_employees_over",
            "voluntary_additional_hours_exempt", "consent_must_be_written", "exemption_note"} <= p.keys()
    assert len(p["exemption_note"].split()) <= 40
    if p["premium_basis"] != "none":
        assert "moved_premium_hours" in p
        assert p.get("reduced_hours_fraction") is not None or p.get("reduced_premium_hours") is not None


def test_call_in_exemption_shapes():
    # Group message required: Seattle, Philadelphia, Oregon (off-shift). One-on-one written OK: Chicago.
    assert ps_rule("PA", "philadelphia").params["exemption_requires_group_message"] is True
    assert ps_rule("OR", None).params["exemption_individual_ok_if_on_shift"] is True
    # No voluntary-acceptance exemption: Berkeley, Evanston, Emeryville (unverified).
    for city in ("berkeley", "emeryville"):
        assert ps_rule("CA", city).params["voluntary_additional_hours_exempt"] is False
    assert ps_rule("IL", "evanston").params["voluntary_additional_hours_exempt"] is False
    # LA and SF exempt only for an absent coworker's hours.
    for city in ("los angeles", "san francisco"):
        assert ps_rule("CA", city).params["exemption_only_for_absent_coworker_hours"] is True
    assert ps_rule("CA", "san francisco").params["under_24h_tiers"][0] == {"max_changed_hours": 4, "premium_hours": 2}
