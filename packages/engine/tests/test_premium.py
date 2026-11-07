"""Predictive-scheduling premiums from law-pack params only (SEMANTICS #17, v1.4 outreach modes)."""
from __future__ import annotations

import pytest
from engine_fixtures import tiny_store
from shiftwright_contracts.models import Jurisdiction
from shiftwright_engine.premium import call_in_premium, extension_premium
from shiftwright_engine.prep import build_prep
from shiftwright_laws import resolve


def _prep(state, city):
    cfg = tiny_store()
    j = Jurisdiction(state=state, city=city)
    cfg = cfg.model_copy(update={"store": cfg.store.model_copy(update={"jurisdiction": j}),
                                 "law_pack": resolve(j, on=cfg.store.week_start)})
    p = build_prep(cfg, with_cands=False)
    return p, p.emps["e3"]


ABSENT = [(480, 720)]  # called-out coworker's lost time


def test_chicago_text_call_in_is_exempt_extension_is_not():
    p, e = _prep("IL", "chicago")
    c = call_in_premium(p, e, 480, 720, "one_to_one", ABSENT, 1)
    assert c.dollars == 0 and c.law_rule_ids == ["IL.chicago.predictive_scheduling.1"] and "exempt" in c.note
    x = extension_premium(p, e, [(720, 780)])
    assert x.dollars == pytest.approx(1 * e.wage_per_hour)


def test_seattle_one_to_one_pays_group_offer_exempt_only_for_absent_hours():
    p, e = _prep("WA", "seattle")
    one = call_in_premium(p, e, 480, 720, "one_to_one", ABSENT, 5)
    assert one.dollars == pytest.approx(1 * e.wage_per_hour)
    grp = call_in_premium(p, e, 480, 720, "group_offer", ABSENT, 5)
    assert grp.dollars == 0 and "mass communication" in grp.note
    # 30 min beyond the absent coworker's hours: pro-rated 0.5 h; under 15 min grace: free.
    part = call_in_premium(p, e, 480, 750, "group_offer", ABSENT, 5)
    assert part.dollars == pytest.approx(0.5 * e.wage_per_hour)
    tiny = call_in_premium(p, e, 480, 730, "group_offer", ABSENT, 5)
    assert tiny.dollars == 0
    assert call_in_premium(p, e, 480, 720, "group_offer", ABSENT, 1).dollars > 0  # needs 2+ recipients


def test_seattle_group_offer_charges_clock_minutes_past_the_absence():
    """G3: 11:00–18:30 call-in (with an unpaid meal) while the absence ends at 18:00: the 30 clock
    minutes after 18:00 are charged, even though paid minutes minus the overlap would be 0."""
    p, e = _prep("WA", "seattle")
    c = call_in_premium(p, e, 660, 1110, "group_offer", [(364, 1080)], 5)
    assert c.dollars == pytest.approx(0.5 * e.wage_per_hour, abs=0.01)


def test_grace_only_for_changes_shorter_than_grace_minutes():
    """G2: a change of exactly grace_minutes (or more) is charged; only shorter ones are free."""
    p, e = _prep("OR", None)  # grace 30, 1 h premium, no prorate
    assert extension_premium(p, e, [(720, 750)]).dollars == pytest.approx(e.wage_per_hour)
    assert extension_premium(p, e, [(720, 745)]).dollars == 0
    p, e = _prep("WA", "seattle")  # grace 15, prorated
    assert extension_premium(p, e, [(720, 750)]).dollars == pytest.approx(0.5 * e.wage_per_hour, abs=0.01)
    assert extension_premium(p, e, [(720, 735)]).dollars == pytest.approx(0.25 * e.wage_per_hour, abs=0.01)
    assert extension_premium(p, e, [(720, 730)]).dollars == 0


def test_sf_extension_covering_absent_coworker_is_exempt():
    """SF `coworker_absence_exempt` (applies to call-ins and extensions in the law data)."""
    p, e = _prep("CA", "san francisco")
    assert extension_premium(p, e, [(540, 660)], [(364, 990)]).dollars == 0
    assert extension_premium(p, e, [(990, 1050)], [(364, 990)]).dollars > 0


def test_berkeley_call_in_always_pays():
    p, e = _prep("CA", "berkeley")
    assert call_in_premium(p, e, 480, 720, "group_offer", ABSENT, 5).dollars == pytest.approx(e.wage_per_hour)


def test_no_pack_rule_no_premium():
    p, e = _prep("TX", None)
    assert call_in_premium(p, e, 480, 720, "one_to_one", ABSENT, 1).dollars == 0
    assert extension_premium(p, e, [(720, 780)]).dollars == 0
