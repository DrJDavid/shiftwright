"""v1.5: tipped pay (#20), sector applicability (#19), minor_prohibited_roles age_min (#21)."""
from __future__ import annotations

from engine_fixtures import tiny_store, with_law
from shiftwright_contracts.models import LawRule, LawRuleType, Sector
from shiftwright_engine import solve_week
from shiftwright_engine.prep import build_prep, sector_applies
from shiftwright_validator import validate


def _bad(cfg, s):
    return [v.message for v in validate(cfg, s).violations if v.severity == "hard" or v.code.value == "metrics_mismatch"]


def test_tipped_shifts_pay_the_tipped_wage_and_agree_with_validator():
    cfg = tiny_store()
    roles = [r.model_copy(update={"tipped": r.id == "cashier"}) for r in cfg.roles]
    emps = [e.model_copy(update={"tipped_wage_per_hour": 9.0}) if e.id in ("e3", "e6") else e for e in cfg.employees]
    cfg = cfg.model_copy(update={"roles": roles, "employees": emps})
    s = solve_week(cfg, time_limit_s=10)
    assert s.status in ("optimal", "feasible")
    assert _bad(cfg, s) == []
    p = build_prep(cfg, with_cands=False)
    e3 = next(e for e in cfg.employees if e.id == "e3")
    assert all(p.shift_rate(e3, [g.role_id for g in sh.segments]) == 9.0 for sh in s.shifts if sh.employee_id == "e3")


def test_restaurant_demo_agrees_with_validator():
    from shiftwright_scenarios import load_demo_store

    cfg = with_law(load_demo_store("restaurant"))
    s = solve_week(cfg, time_limit_s=15)
    assert _bad(cfg, s) == []
    ages = {e.id: e.age for e in cfg.employees}
    tags = cfg.role_tags
    for sh in s.shifts:
        for g in sh.segments:
            if "alcohol_service" in tags.get(g.role_id, []):
                assert ages[sh.employee_id] >= 21  # Chicago: under-21 alcohol_service banned


def _rule(applies_to):
    return LawRule(id="X.1", type=LawRuleType.predictive_scheduling, params={"applies_to": applies_to},
                   summary="", source={"url": "https://example.com", "retrieved_on": "2026-11-07"},
                   jurisdiction_level="city")


def test_sector_applicability():
    try:
        r_food, r_retail, r_both = _rule("food"), _rule("retail"), _rule("both")
    except Exception:  # LawRule shape differs: test the helper with a stand-in
        class R:  # noqa: D401
            def __init__(self, a):
                self.params = {"applies_to": a}
        r_food, r_retail, r_both = R("food"), R("retail"), R("both")
    assert sector_applies(r_food, Sector.food) and not sector_applies(r_food, Sector.retail)
    assert sector_applies(r_retail, Sector.retail) and not sector_applies(r_retail, Sector.food)
    assert sector_applies(r_both, Sector.hospitality)
    assert sector_applies(r_food, None) and sector_applies(r_food, Sector.other)


def test_minor_prohibited_age_min():
    cfg = tiny_store()
    pack = cfg.law_pack
    rule = next(r for r in pack.rules if r.type == LawRuleType.minor_prohibited_roles)
    rule2 = rule.model_copy(update={"id": "T.band", "params": {**rule.params, "age_below": 21, "age_min": 18,
                                                                    "role_tags": rule.params["role_tags"]}})
    others = [r for r in pack.rules if r.type != LawRuleType.minor_prohibited_roles]
    emps = cfg.employees
    # e4 (17) trained on pit_operator: only the age_min=18 band rule -> not banned by it (min_age still applies)
    cfg2 = cfg.model_copy(update={"law_pack": pack.model_copy(update={"rules": others + [rule2]}),
                                  "roles": [r.model_copy(update={"min_age": 0}) for r in cfg.roles]})
    p = build_prep(cfg2, with_cands=False)
    e4 = next(e for e in emps if e.id == "e4")
    assert e4.age == 17 and "pit_operator" in p.allowed_roles["e4"]
    cfg3 = cfg2.model_copy(update={"employees": [e.model_copy(update={"age": 19}) if e.id == "e4" else e for e in emps]})
    p3 = build_prep(cfg3, with_cands=False)
    assert "pit_operator" not in p3.allowed_roles["e4"]
