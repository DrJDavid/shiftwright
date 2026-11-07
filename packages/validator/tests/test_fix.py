"""validate_fix (SEMANTICS #16, #17). Hand-built plans on the conftest store; premium amounts
checked against hand calculations from each real law pack's params (data/laws)."""
from __future__ import annotations

import pytest

from shiftwright_contracts.models import (
    AvailabilityEntry,
    AvailabilityKind,
    CallOut,
    FixAction,
    FixPlan,
    FixRequest,
    Jurisdiction,
    LawRuleType,
    Lever,
    OutreachCandidate,
    RoleSegment,
    Schedule,
    Shift,
    ViolationCode,
)
from shiftwright_validator import validate, validate_fix
from shiftwright_validator.fix import diff, price_change

V = ViolationCode
MON = 0


def codes(report) -> set:
    return {v.code for v in report.violations if v.severity == "hard"}


def simple(sid, eid, start, end, role, day=MON) -> Shift:
    return Shift(id=sid, employee_id=eid, day=day, start=start, end=end,
                 segments=[RoleSegment(role_id=role, start=start, end=end)])


def copy_without(schedule: Schedule, *shift_ids) -> Schedule:
    out = schedule.model_copy(deep=True)
    out.shifts = [s for s in out.shifts if s.id not in shift_ids]
    out.produced_by = "engine"
    return out


def build(config, perfect, now=480, mode=None, declined=()):
    """Cam (e2, cashier Mon 09-13, shift s3) calls out at 08:00. Plan: call in Sam (e3) for 09-13.
    Nothing else changes."""
    request = FixRequest(config=config, schedule=perfect, day=MON, now=now,
                         callouts=[CallOut(employee_id="e2", day=MON, reported_at=now)],
                         outreach_mode=mode, declined_employee_ids=list(declined))
    none = copy_without(perfect, "s3")
    callin = simple("c1", "e3", 540, 780, "cashier")
    all_ = copy_without(perfect, "s3")
    all_.shifts.append(callin)
    plan = FixPlan(actions=[], outreach_mode=mode or "one_to_one",
                   outreach_queue=[OutreachCandidate(rank=1, employee_id="e3", proposed_shift=callin,
                                                     added_cost_dollars=64, est_accept_prob=0.5, why="t")],
                   schedule_if_all_accept=all_, schedule_if_none_accept=none,
                   coverage_before_pct=80, coverage_after_best_pct=100, coverage_after_worst_pct=80)
    return request, plan


def test_clean_plan_passes(config, perfect):
    request, plan = build(config, perfect)
    report = validate_fix(request, plan)
    assert report.violations == [], [v.message for v in report.violations]
    assert report.recomputed_metrics.coverage_pct == pytest.approx(100.0)


def test_change_before_now_is_malformed(config, perfect):
    request, plan = build(config, perfect, now=600)
    for sched in (plan.schedule_if_all_accept, plan.schedule_if_none_accept):
        s1 = next(s for s in sched.shifts if s.id == "s1")  # Lee 09:00-13:00 already working at 10:00
        s1.start = 570
        s1.segments = [RoleSegment(role_id="leader", start=570, end=780)]
    report = validate_fix(request, plan)
    assert V.malformed in codes(report)
    assert any("before now" in v.message for v in report.violations)


def test_change_on_another_day_is_malformed(config, perfect):
    request, plan = build(config, perfect)
    s5 = next(s for s in plan.schedule_if_none_accept.shifts if s.id == "s5")  # Tuesday
    s5.end = 750
    s5.segments = [RoleSegment(role_id="cashier", start=540, end=750)]
    assert any("another day" in v.message for v in validate_fix(request, plan).violations)


def test_called_out_employee_still_working(config, perfect):
    request, plan = build(config, perfect)
    plan.schedule_if_none_accept.shifts.append(simple("s3", "e2", 540, 780, "cashier"))
    report = validate_fix(request, plan)
    assert V.unavailable in codes(report)
    assert any("called out" in v.message for v in report.violations)


def test_declined_employee_is_not_asked_again(config, perfect):
    request, plan = build(config, perfect, declined=["e3"])
    assert any("already declined" in v.message for v in validate_fix(request, plan).violations)


def test_outreach_mode_must_match_request(config, perfect):
    request, plan = build(config, perfect, mode="group_offer")
    plan.outreach_mode = "one_to_one"
    assert any("outreach_mode" in v.message for v in validate_fix(request, plan).violations)


def test_action_missing_from_schedule(config, perfect):
    request, plan = build(config, perfect)
    plan.actions.append(FixAction(lever=Lever.extend, employee_id="e6", role_id="leader", start=720,
                                  end=780, added_cost_dollars=24, rationale="t"))
    assert any("not in schedule_if_none_accept" in v.message for v in validate_fix(request, plan).violations)


def test_callin_not_charged_preferred_off(config, perfect):
    """SEMANTICS #16: Sam prefers Monday morning off ($5/h), but a call-in isn't charged it."""
    config.employees[2].availability = [AvailabilityEntry(weekday=MON, start=540, end=780,
                                                          kind=AvailabilityKind.preferred_off,
                                                          weight_dollars=5)]
    request, plan = build(config, perfect)
    assert validate(config, plan.schedule_if_all_accept).recomputed_metrics.soft_penalty_dollars == 20
    report = validate_fix(request, plan)
    assert report.passed and report.recomputed_metrics.soft_penalty_dollars == 0


# --------------------------------------------------------------------------- #
# Premiums with a TEST-ONLY rule
# --------------------------------------------------------------------------- #
def add_test_rule(config, kit, **params):
    base = {"notice_days": 14, "applies_to": "both", "applies_if_employees_over": None,
            "premium_basis": "regular_rate", "change_premium_hours": 1}
    config.law_pack.rules.append(kit.test_law("TEST.fww", LawRuleType.predictive_scheduling,
                                              {**base, **params}))


def test_callin_premium_mismatch_is_reported(config, perfect, kit):
    add_test_rule(config, kit)  # no exemptions: a call-in costs 1 h x Sam's $16
    request, plan = build(config, perfect)
    report = validate_fix(request, plan)
    hits = [v for v in report.violations if v.code == V.metrics_mismatch]
    assert len(hits) == 1 and "call-in #1 e3" in hits[0].message and "$16.00" in hits[0].message
    assert hits[0].law_rule_id == "TEST.fww"
    plan.outreach_queue[0].premium_pay_dollars = 16.0
    assert validate_fix(request, plan).violations == []


def test_schedule_metrics_must_include_premiums(config, perfect, kit):
    from shiftwright_validator import recompute_metrics

    add_test_rule(config, kit)
    request, plan = build(config, perfect)
    plan.outreach_queue[0].premium_pay_dollars = 16.0
    plan.schedule_if_all_accept.metrics = recompute_metrics(config, plan.schedule_if_all_accept)
    report = validate_fix(request, plan)
    assert [v.message for v in report.violations if v.code == V.metrics_mismatch] == [
        "[schedule_if_all_accept] Claimed premium_pay_dollars 0 but recomputed 16.",
        "[schedule_if_all_accept] Claimed objective_dollars 515 but recomputed 531."]
    assert report.recomputed_metrics.premium_pay_dollars == 16.0


def test_group_offer_exemption(config, perfect, kit):
    add_test_rule(config, kit, voluntary_additional_hours_exempt=True, consent_must_be_written=True,
                  text_message_counts_as_written=True, exemption_requires_group_message=True,
                  exemption_min_recipients=1)
    request, plan = build(config, perfect, mode="group_offer")
    assert validate_fix(request, plan).violations == []          # exempt: $0
    request, plan = build(config, perfect, mode="one_to_one")
    assert codes(validate_fix(request, plan)) == {V.metrics_mismatch}  # one-to-one: $16 due


def test_immediate_extension_is_priced(config, perfect, kit):
    add_test_rule(config, kit, voluntary_additional_hours_exempt=True)
    request, plan = build(config, perfect)
    for sched in (plan.schedule_if_all_accept, plan.schedule_if_none_accept):
        s2 = next(s for s in sched.shifts if s.id == "s2")  # Jo leader 13-17 -> 12-17
        s2.start = 720
        s2.segments = [RoleSegment(role_id="leader", start=720, end=1020)]
    action = FixAction(lever=Lever.extend, employee_id="e6", role_id="leader", start=720, end=780,
                       added_cost_dollars=24, rationale="t")
    plan.actions.append(action)
    hits = [v.message for v in validate_fix(request, plan).violations if v.code == V.metrics_mismatch]
    assert len(hits) == 1 and "e6's immediate changes" in hits[0] and "$24.00" in hits[0]
    action.premium_pay_dollars = 24.0
    assert validate_fix(request, plan).violations == []


def test_validate_fix_never_raises(config, perfect):
    request, plan = build(config, perfect)
    plan.outreach_queue[0].proposed_shift.segments = None  # garbage
    report = validate_fix(request, plan)
    assert report.passed is False


# --------------------------------------------------------------------------- #
# Real law packs: one hand-computed table per jurisdiction (wage $20)
# --------------------------------------------------------------------------- #
laws = pytest.importorskip("shiftwright_laws")

# Monday. Cam (e2, 09-13) calls out at 08:00. Changes priced:
#   ext    Jo (e6, 13-17) extended to 18:00 (+60 min, outside Cam's hours)
#   call1  Sam (e3) called in 09-13 (all inside Cam's hours), one_to_one
#   callg  same, group_offer with 3 recipients
#   cut    Pat (e4, 09-17, 8 h) cut to 09-15 (-2 h), 1 h notice
TABLE = {
    #  jurisdiction                ext  call1 callg  cut
    ("WA", "seattle"):           (20,  20,   0,    20),   # 1 h; group needed; 0.5 x 2 h
    ("IL", "chicago"):           (20,  0,    0,    20),   # text = written consent; 0.5 x 2 h (<24 h)
    ("IL", "evanston"):          (20,  20,   20,   80),   # no voluntary exemption; min(4, 1.0 x 8 h)
    ("CA", "los angeles"):       (20,  0,    0,    20),   # absent-coworker hours exempt; 0.5 x 2 h
    ("CA", "san francisco"):     (40,  0,    0,    40),   # <24 h tier: 2 h; coworker absence exempt
    ("CA", "berkeley"):          (20,  20,   20,   40),   # no voluntary exemption; 1.0 x 2 h
    ("CA", "emeryville"):        (20,  20,   20,   80),   # min(4, 1.0 x 8 h scheduled)
    ("PA", "philadelphia"):      (20,  20,   0,    20),   # group needed; 0.5 x 2 h
    ("NY", "new york"):          (0,   0,    0,    0),    # premium_basis none (prohibitions)
    ("OR", None):                (20,  20,   20,   20),   # text isn't written consent
}


def priced(config, kit_change, via_call_in, mode, queue_len=3):
    request = FixRequest(config=config, schedule=kit_change["schedule"], day=MON, now=480,
                         callouts=[CallOut(employee_id="e2", day=MON, reported_at=480)])
    eid, before, after = kit_change["change"]
    return price_change(request, diff(eid, before, after), via_call_in, mode, queue_len).dollars


@pytest.mark.parametrize("jur,expected", list(TABLE.items()), ids=[f"{s}-{c}" for s, c in TABLE])
def test_premiums_by_jurisdiction(config, perfect, jur, expected):
    config.law_pack = laws.resolve(Jurisdiction(state=jur[0], city=jur[1]))
    assert any(r.type == LawRuleType.predictive_scheduling for r in config.law_pack.rules)
    for e in config.employees:
        e.wage_per_hour = 20.0
    ext = {"schedule": perfect, "change": ("e6", set(range(780, 1020)), set(range(780, 1080)))}
    call = {"schedule": perfect, "change": ("e3", set(), set(range(540, 780)))}
    cut = {"schedule": perfect, "change": ("e4", set(range(540, 1020)), set(range(540, 900)))}
    got = (priced(config, ext, False, "one_to_one"),
           priced(config, call, True, "one_to_one"),
           priced(config, call, True, "group_offer"),
           priced(config, cut, False, "one_to_one"))
    assert got == pytest.approx(expected)


def test_employer_below_threshold_is_not_covered(config, perfect):
    config.law_pack = laws.resolve(Jurisdiction(state="WA", city="seattle"))  # over 499
    config.store.employer_employee_count = 120
    change = {"schedule": perfect, "change": ("e6", set(range(780, 1020)), set(range(780, 1080)))}
    assert priced(config, change, False, "one_to_one") == 0
    config.store.employer_employee_count = None  # unknown: assume covered (SEMANTICS #17)
    assert priced(config, change, False, "one_to_one") > 0


def test_plain_validate_accepts_unverified_fww_premium(config, perfect, kit):
    """validate() has no posted schedule: with predictive_scheduling rules a claimed premium above
    the recomputed one is left to validate_fix; one below it is still a mismatch."""
    from shiftwright_validator import recompute_metrics

    add_test_rule(config, kit)
    m = recompute_metrics(config, perfect)
    perfect.metrics = m.model_copy(update={"premium_pay_dollars": 16.0,
                                           "objective_dollars": m.objective_dollars + 16})
    assert validate(config, perfect).violations == []
    config.law_pack.rules.pop()  # no predictive-scheduling rule: the $16 is unexplained
    assert {v.code for v in validate(config, perfect).violations} == {V.metrics_mismatch}


def test_unexplained_change_is_malformed(config, perfect):
    request, plan = build(config, perfect)
    s2 = next(s for s in plan.schedule_if_all_accept.shifts if s.id == "s2")  # Jo 13-17 -> 12:30-17
    s2.start = 750
    s2.segments = [RoleSegment(role_id="leader", start=750, end=1020)]
    hits = [v.message for v in validate_fix(request, plan).violations if v.code == V.malformed]
    assert hits == ["[schedule_if_all_accept] e6's hours change on day 0 (+30 / -0 min) but no action "
                    "or outreach candidate names them."]
