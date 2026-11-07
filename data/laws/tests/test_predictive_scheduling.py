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
