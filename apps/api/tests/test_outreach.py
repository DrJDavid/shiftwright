"""Fix + mock outreach. engine.fix_day and validator.validate are faked here (WS1/WS2 not merged)."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from api_helpers import tiny_config
from shiftwright_api import integrations
from shiftwright_api.main import create_app
from shiftwright_api.messenger import interpret_keywords, twilio_signature_valid
from shiftwright_api.models import OutreachState
from shiftwright_contracts.models import (
    FixPlan,
    FixRequest,
    OutreachCandidate,
    RoleSegment,
    Schedule,
    Shift,
    ValidationReport,
)


def _cand(rank, emp, cfg):
    sh = Shift(id=f"s_{emp}", employee_id=emp, day=5, start=600, end=840,
               segments=[RoleSegment(role_id="cashier", start=600, end=840)])
    return OutreachCandidate(rank=rank, employee_id=emp, proposed_shift=sh, added_cost_dollars=64.0,
                             est_accept_prob=0.5, why="trained, under max hours")


@pytest.fixture
def fake_engine(monkeypatch):
    calls: list[FixRequest] = []

    def fix_day(req: FixRequest, time_limit_s: float = 8) -> FixPlan:
        calls.append(req)
        accepted = {s.employee_id for s in req.schedule.shifts}
        queue = [] if accepted else [_cand(i + 1, e, req.config) for i, e in enumerate(
            [e for e in ("e0", "e1") if e not in req.declined_employee_ids])]
        s = req.schedule
        return FixPlan(actions=[], outreach_queue=queue, schedule_if_all_accept=s, schedule_if_none_accept=s,
                       coverage_before_pct=50.0, coverage_after_best_pct=100.0, coverage_after_worst_pct=50.0)

    def validate(config, schedule):
        hours = sum((s.end - s.start) / 60 for s in schedule.shifts)
        m = schedule.metrics.model_copy(update={"total_hours": hours, "coverage_pct": 100.0 if hours else 0.0})
        return ValidationReport(passed=True, hard_count=0, violations=[], recomputed_metrics=m)

    monkeypatch.setattr(integrations, "fix_day", fix_day)
    monkeypatch.setattr(integrations, "validate", validate)
    return calls


@pytest.fixture
def oclient(settings, fake_engine):
    settings.outreach_timeout_s = 5
    with TestClient(create_app(settings=settings)) as c:
        sid = c.post("/api/stores", json={"name": "Store #0417", "jurisdiction": {"state": "TX"}}).json()["store"]["id"]
        cfg = tiny_config().model_copy(deep=True)
        cfg.store.id = sid
        assert c.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json")).status_code == 200
        assert c.post(f"/api/stores/{sid}/solve", json={}).status_code == 200
        yield c, sid, cfg


def _wait(c, sid, pred, timeout=2.0) -> OutreachState:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = OutreachState.model_validate(c.get(f"/api/stores/{sid}/outreach").json())
        if pred(st):
            return st
        time.sleep(0.02)
    raise AssertionError(f"timed out; last state {st}")


def _start(c, sid):
    r = c.post(f"/api/stores/{sid}/fix", json={"callouts": [{"employee_id": "e2", "day": 5, "reported_at": 364}],
                                               "day": 5, "now": 364})
    assert r.status_code == 200, r.text
    plan = r.json()
    FixPlan.model_validate(plan)
    st = OutreachState.model_validate(c.post(f"/api/stores/{sid}/outreach/start", json={"plan_id": plan["plan_id"]}).json())
    assert st.status == "texting"
    return st


def test_decline_then_accept(oclient):
    c, sid, cfg = oclient
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    first = st.messages[-1]
    assert first.to_employee_id == "e0" and first.body.endswith("Reply YES or NO")
    assert "$16.00/hr" in first.body

    t0 = time.time()
    c.post("/api/sms/mock-reply", json={"from_phone": first.to_phone, "body": "sorry can't today"})
    st = _wait(c, sid, lambda s: any(getattr(m, "to_employee_id", None) == "e1" for m in s.messages))
    assert time.time() - t0 < 2.0, "rank 2 must be texted within 2 s of a decline"
    assert st.messages[1].interpreted_as == "decline"

    second = st.messages[-1]
    c.post("/api/sms/mock-reply", json={"from_phone": second.to_phone, "body": "YES"})
    st = _wait(c, sid, lambda s: s.status == "filled")
    assert st.accepted_employee_ids == ["e1"]
    assert [s.employee_id for s in st.schedule.shifts] == ["e1"]
    assert st.schedule.metrics.total_hours == 4.0      # recomputed by the validator
    latest = Schedule.model_validate(c.get(f"/api/stores/{sid}/schedule").json()["schedule"])
    assert [s.employee_id for s in latest.shifts] == ["e1"]


def test_question_is_forwarded_and_keeps_waiting(oclient):
    c, sid, _ = oclient
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "what time does it end?"})
    st = _wait(c, sid, lambda s: len(s.messages) == 2)
    assert st.messages[-1].interpreted_as == "question"
    assert st.current_rank == 1 and st.status == "texting"


def test_fix_without_engine_is_503(settings):
    with TestClient(create_app(settings=settings)) as c:
        sid = c.post("/api/stores", json={"name": "x", "jurisdiction": {"state": "TX"}}).json()["store"]["id"]
        c.post(f"/api/stores/{sid}/solve", json={})
        r = c.post(f"/api/stores/{sid}/fix", json={"callouts": [], "day": 5, "now": 300})
        assert r.status_code == 503


@pytest.mark.parametrize("body,want", [("YES", "accept"), ("y", "accept"), ("Sure!", "accept"), ("no", "decline"),
                                        ("Can't, sorry", "decline"), ("is it paid OT?", "question"), ("hmm", None)])
def test_keyword_interpretation(body, want):
    assert interpret_keywords(body) == want


def test_twilio_signature():
    import base64, hashlib, hmac
    url, params = "https://x.example/api/sms/inbound", {"From": "+15125550101", "Body": "yes"}
    payload = url + "".join(k + params[k] for k in sorted(params))
    sig = base64.b64encode(hmac.new(b"tok", payload.encode(), hashlib.sha1).digest()).decode()
    assert twilio_signature_valid("tok", url, params, sig)
    assert not twilio_signature_valid("tok", url, params, "bad")
