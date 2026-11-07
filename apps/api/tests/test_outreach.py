"""Fix + mock outreach. engine.solve_week/fix_day and validator.validate are faked here so the test
is deterministic whether or not the real WS1/WS2 packages are installed."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from api_helpers import signup, tiny_config
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


def _cashiers(cfg):
    """First two cashier-trained employees in the loaded fixture (e.g. tiny_store.json), in id order."""
    return [e.id for e in sorted(cfg.employees, key=lambda e: e.id) if "cashier" in e.trained_role_ids][:2]


@pytest.fixture
def fake_engine(monkeypatch):
    calls: list[FixRequest] = []

    def fix_day(req: FixRequest, time_limit_s: float = 8) -> FixPlan:
        calls.append(req)
        accepted = {s.employee_id for s in req.schedule.shifts if s.id.startswith("s_")}  # our proposed shifts
        queue = [] if accepted else [_cand(i + 1, e, req.config) for i, e in enumerate(
            [e for e in _cashiers(req.config) if e not in req.declined_employee_ids])]
        s = req.schedule
        return FixPlan(actions=[], outreach_queue=queue, schedule_if_all_accept=s, schedule_if_none_accept=s,
                       coverage_before_pct=50.0, coverage_after_best_pct=100.0, coverage_after_worst_pct=50.0,
                       outreach_mode=req.outreach_mode or "one_to_one")

    def validate(config, schedule):
        hours = sum((s.end - s.start) / 60 for s in schedule.shifts)
        m = schedule.metrics.model_copy(update={"total_hours": hours, "coverage_pct": 100.0 if hours else 0.0})
        return ValidationReport(passed=True, hard_count=0, violations=[], recomputed_metrics=m)

    monkeypatch.setattr(integrations, "solve_week", lambda config, time_limit_s=20, previous=None:
                        integrations._stub_solve(config))  # empty base schedule, as with the stub engine
    monkeypatch.setattr(integrations, "fix_day", fix_day)
    monkeypatch.setattr(integrations, "validate", validate)
    return calls


@pytest.fixture
def oclient(settings, fake_engine):
    settings.outreach_timeout_s = 5
    with TestClient(create_app(settings=settings)) as c:
        signup(c)
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
    r = c.post(f"/api/stores/{sid}/fix", json={"callouts": [{"employee_id": "e9", "day": 5, "reported_at": 364}],
                                               "day": 5, "now": 364})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert FixPlan.model_validate(plan).plan_id == plan["plan_id"]
    st = OutreachState.model_validate(c.post(f"/api/stores/{sid}/outreach/start", json={"plan_id": plan["plan_id"]}).json())
    assert st.status == "texting"
    return st


def test_decline_then_accept(oclient):
    c, sid, cfg = oclient
    rank1, rank2 = _cashiers(cfg)
    wage = {e.id: e.wage_per_hour for e in cfg.employees}
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    first = st.messages[-1]
    assert first.to_employee_id == rank1 and first.body.endswith("Reply YES or NO")
    assert f"${wage[rank1]:.2f}/hr" in first.body

    t0 = time.time()
    c.post("/api/sms/mock-reply", json={"from_phone": first.to_phone, "body": "sorry can't today"})
    st = _wait(c, sid, lambda s: any(getattr(m, "to_employee_id", None) == rank2 for m in s.messages))
    assert time.time() - t0 < 2.0, "rank 2 must be texted within 2 s of a decline"
    assert st.messages[1].interpreted_as == "decline"

    second = st.messages[-1]
    c.post("/api/sms/mock-reply", json={"from_phone": second.to_phone, "body": "YES"})
    st = _wait(c, sid, lambda s: s.status == "filled")
    assert st.accepted_employee_ids == [rank2]
    assert [s.employee_id for s in st.schedule.shifts] == [rank2]
    assert st.schedule.metrics.total_hours == 4.0      # recomputed by the validator
    latest = Schedule.model_validate(c.get(f"/api/stores/{sid}/schedule").json()["schedule"])
    assert [s.employee_id for s in latest.shifts] == [rank2]


def test_question_is_forwarded_and_keeps_waiting(oclient):
    c, sid, _ = oclient
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "what time does it end?"})
    st = _wait(c, sid, lambda s: len(s.messages) == 3)
    assert st.messages[1].interpreted_as == "question"
    answer = st.messages[2]
    assert answer.to_employee_id == st.messages[0].to_employee_id and "Sat 10 am to 2 pm" in answer.body
    assert st.current_rank == 1 and st.status == "texting"


def test_fix_without_engine_is_503(settings):
    import shiftwright_engine
    if hasattr(shiftwright_engine, "fix_day"):
        pytest.skip("real fix_day is available")
    with TestClient(create_app(settings=settings)) as c:
        signup(c)
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


# --------------------------------------------------------------------------- security / limits
def test_twilio_only_texts_allowlisted_numbers(monkeypatch):
    import asyncio
    from shiftwright_api import messenger as m

    posted = []

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def post(self, url, auth=None, data=None):
            posted.append(data["To"])
            return httpx_resp()

    class httpx_resp:
        status_code = 201
        def json(self): return {"sid": "SM1"}

    monkeypatch.setattr(m.httpx, "AsyncClient", FakeClient)
    tw = m.TwilioMessenger("AC1", "tok", "+15125550000", allowlist=["+1 (512) 555-0101"])
    cfg = tiny_config()
    ok = cfg.employees[0].model_copy(update={"phone": "+15125550101"})
    bad = cfg.employees[1].model_copy(update={"phone": "+15125550199"})
    asyncio.run(tw.send(ok, "hi"))
    with pytest.raises(m.RecipientBlocked):
        asyncio.run(tw.send(bad, "hi"))
    assert posted == ["+15125550101"]


def test_blocked_recipient_is_skipped(oclient):
    from shiftwright_api.messenger import RecipientBlocked
    c, sid, cfg = oclient
    rank1, rank2 = _cashiers(cfg)
    mgr = c.app.state.outreach
    real_send = mgr.messenger.send

    async def send(emp, body, outreach_rank=None):
        if emp.id == rank1:
            raise RecipientBlocked("not on allowlist")
        return await real_send(emp, body, outreach_rank)

    mgr.messenger.send = send
    _start(c, sid)
    st = _wait(c, sid, lambda s: any(getattr(m, "to_employee_id", None) == rank2 for m in s.messages))
    assert not any(getattr(m, "to_employee_id", None) == rank1 for m in st.messages)
    assert st.messages[0].from_phone == "system"


def test_one_active_outreach_per_store_and_cancel(oclient):
    c, sid, _ = oclient
    _start(c, sid)
    _wait(c, sid, lambda s: s.current_rank == 1)
    plan = c.post(f"/api/stores/{sid}/fix", json={"callouts": [], "day": 5, "now": 364}).json()
    assert c.post(f"/api/stores/{sid}/outreach/start", json={"plan_id": plan["plan_id"]}).status_code == 409
    st = OutreachState.model_validate(c.post(f"/api/stores/{sid}/outreach/cancel").json())
    assert st.status == "exhausted"
    assert c.post(f"/api/stores/{sid}/outreach/start", json={"plan_id": plan["plan_id"]}).status_code == 200


def test_text_rate_limit(oclient):
    c, sid, _ = oclient
    c.app.state.outreach.max_texts_per_hour = 1
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "no"})
    st = _wait(c, sid, lambda s: s.status == "exhausted")
    assert sum(1 for m in st.messages if getattr(m, "to_employee_id", None)) == 1
    assert "text limit" in st.messages[-1].body


def test_demo_key_guards_mutations(settings):
    settings.demo_key = "s3cret"
    settings.auth_required = False  # DEMO_KEY only applies when accounts are off
    with TestClient(create_app(settings=settings)) as c:
        assert c.get("/api/health").json()["demo_key_required"] is True
        body = {"name": "x", "jurisdiction": {"state": "TX"}}
        assert c.post("/api/stores", json=body).status_code == 401
        assert c.post("/api/stores", json=body, headers={"X-Demo-Key": "wrong"}).status_code == 401
        r = c.post("/api/stores", json=body, headers={"X-Demo-Key": "s3cret"})
        assert r.status_code == 200
        sid = r.json()["store"]["id"]
        assert c.get(f"/api/stores/{sid}/config").status_code == 200
        assert c.post(f"/api/stores/{sid}/solve", json={}).status_code == 401
        assert c.post("/api/sms/mock-reply", json={"from_phone": "1", "body": "y"}).status_code == 401
        assert c.post("/api/sms/inbound", data={"From": "1", "Body": "y"}).status_code == 200  # mock: no signature


def test_outreach_stream_pushes_snapshots_until_filled(oclient):
    import json
    import threading
    c, sid, cfg = oclient
    rank1, rank2 = _cashiers(cfg)
    _start(c, sid)
    _wait(c, sid, lambda s: s.current_rank == 1)
    seen: list[OutreachState] = []

    def reply():
        st = _wait(c, sid, lambda s: s.current_rank == 1)
        time.sleep(0.1)
        c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "no"})
        st = _wait(c, sid, lambda s: getattr(s.messages[-1], "to_employee_id", None) == rank2)
        c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "yes"})

    t = threading.Thread(target=reply)
    t.start()
    with c.stream("GET", f"/api/stores/{sid}/outreach/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                seen.append(OutreachState.model_validate(json.loads(line[6:])))
    t.join()
    assert seen[0].status == "texting" and seen[-1].status == "filled"
    assert len(seen) >= 3 and seen[-1].accepted_employee_ids == [rank2]


def test_outreach_stream_idle_store_closes(client):
    from api_helpers import make_store
    sid = make_store(client)["store"]["id"]
    r = client.get(f"/api/stores/{sid}/outreach/stream")
    assert r.text.startswith("event: state\ndata: ") and '"status":"idle"' in r.text


# --------------------------------------------------------------------------- simulated replies (mock)
@pytest.fixture
def auto_client(settings, fake_engine):
    settings.outreach_timeout_s = 5
    settings.mock_autoreply = "script"
    settings.mock_reply_delay_s = 0.05
    with TestClient(create_app(settings=settings)) as c:
        signup(c)
        sid = c.post("/api/stores", json={"name": "Store #0417", "jurisdiction": {"state": "TX"}}).json()["store"]["id"]
        cfg = tiny_config().model_copy(deep=True)
        cfg.store.id = sid
        assert c.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json")).status_code == 200
        assert c.post(f"/api/stores/{sid}/solve", json={}).status_code == 200
        yield c, sid, cfg


def test_scripted_autoreply_demo_thread(auto_client):
    c, sid, cfg = auto_client
    rank1, rank2 = _cashiers(cfg)
    assert c.get("/api/health").json()["mock_autoreply"] == "script"
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.status == "filled", timeout=5)
    thread = [(getattr(m, "to_employee_id", None) or "in", m.body) for m in st.messages]
    assert [b for _, b in thread[1:2]] == ["Sorry, can't today"]
    assert thread[2][0] == rank2 and thread[3][1] == "What time?" and thread[4][0] == rank2  # auto answer
    assert thread[5][1] == "Yes I can" and st.accepted_employee_ids == [rank2]
    times = [getattr(m, "sent_at", None) or m.received_at for m in st.messages]
    assert times == sorted(times)


def test_manual_reply_overrides_autoreply(auto_client):
    c, sid, cfg = auto_client
    rank1, _ = _cashiers(cfg)
    c.app.state.outreach.reply_delay_s = 2.0
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "yes!"})
    st = _wait(c, sid, lambda s: s.status == "filled")
    assert st.accepted_employee_ids == [rank1]
    assert [m.body for m in st.messages if not getattr(m, "to_employee_id", None)] == ["yes!"]


def test_prob_autoreply_is_seeded():
    from shiftwright_api.messenger import MockMessenger
    from shiftwright_api.outreach import OutreachManager, Run
    mgr = OutreachManager(db=None, messenger=MockMessenger(), llm=None, timeout_s=1, autoreply="prob", seed=1)
    cfg = tiny_config()
    run = Run(store_id="s", plan_id="p", plan=None, callouts=[], day=5, now=0, schedule=None, state=OutreachState())
    sure, never = _cand(1, "a", cfg), _cand(2, "b", cfg)
    sure.est_accept_prob, never.est_accept_prob = 1.0, 0.0
    assert mgr._script(run, sure) == ["Yes I can"] and mgr._script(run, never) == ["Sorry, can't today"]
    mid = _cand(3, "c", cfg)
    assert mgr._script(run, mid) == mgr._script(run, mid)


def test_autoreply_never_applies_to_twilio():
    from shiftwright_api.messenger import TwilioMessenger
    from shiftwright_api.outreach import OutreachManager
    tw = TwilioMessenger("AC", "tok", "+15125550000")
    assert OutreachManager(db=None, messenger=tw, llm=None, timeout_s=1, autoreply="script").autoreply == "off"


# --------------------------------------------------------------------------- predictive scheduling modes
def _client_in(settings, state, city):
    settings.outreach_timeout_s = 5
    c = TestClient(create_app(settings=settings))
    c.__enter__()
    signup(c)
    sid = c.post("/api/stores", json={"name": "Store", "jurisdiction": {"state": state}}).json()["store"]["id"]
    cfg = tiny_config().model_copy(deep=True)
    cfg.store.id = sid
    cfg.store.jurisdiction = cfg.store.jurisdiction.model_copy(update={"state": state, "city": city})
    for e in cfg.employees:
        e.wage_per_hour = max(e.wage_per_hour, 21.0)  # above local minimum wage
    assert c.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json")).status_code == 200
    assert c.post(f"/api/stores/{sid}/solve", json={}).status_code == 200
    return c, sid, cfg


def test_validation_stored_after_accept(oclient):
    c, sid, cfg = oclient
    _start(c, sid)
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "yes"})
    _wait(c, sid, lambda s: s.status == "filled")
    body = c.get(f"/api/stores/{sid}/schedule").json()
    assert body["validation"] is not None and body["validation"]["passed"] is True


def test_seattle_group_offer(settings, fake_engine):
    c, sid, cfg = _client_in(settings, "WA", "seattle")
    try:
        rank1, rank2 = _cashiers(cfg)
        _start(c, sid)
        assert fake_engine[-1].outreach_mode == "group_offer"  # API asked the engine to price a group offer
        st = _wait(c, sid, lambda s: len(s.messages) >= 2)
        assert st.mode == "group_offer" and st.premium["status"] == "exempt" and st.premium["law_rule_ids"]
        assert {m.to_employee_id for m in st.messages} == {rank1, rank2}
        assert all("mass communication" in m.body and "voluntary" in m.body and "compensation" in m.body
                   and m.body.endswith("Reply YES or NO") for m in st.messages)
        assert sorted(st.waiting_employee_ids) == sorted([rank1, rank2])
        to2 = next(m for m in st.messages if m.to_employee_id == rank2)
        c.post("/api/sms/mock-reply", json={"from_phone": to2.to_phone, "body": "YES"})
        st = _wait(c, sid, lambda s: s.status == "filled")
        assert st.accepted_employee_ids == [rank2]
        filled = [m for m in st.messages if getattr(m, "to_employee_id", None) == rank1][-1]
        assert "filled" in filled.body
    finally:
        c.__exit__(None, None, None)


def test_chicago_text_says_voluntary(settings, fake_engine):
    c, sid, cfg = _client_in(settings, "IL", "chicago")
    try:
        _start(c, sid)
        st = _wait(c, sid, lambda s: s.current_rank == 1)
        assert st.mode == "one_to_one" and st.premium["status"] == "exempt"
        assert len(st.messages) == 1 and "voluntary" in st.messages[0].body
    finally:
        c.__exit__(None, None, None)


def test_policy_owed_when_no_exemption():
    from shiftwright_api.predictive import policy
    from shiftwright_contracts.models import LawPack, LawRule
    cfg = tiny_config()
    rule = LawRule.model_validate({"id": "X.ps.1", "jurisdiction": {"state": "XX"}, "level": "city",
                                   "type": "predictive_scheduling", "params": {"notice_days": 14},
                                   "summary": "s", "citation": {"url": "u", "title": "t", "excerpt": "e",
                                                                "last_verified": "2026-11-06"},
                                   "confidence": "high"})
    pol = policy(cfg, LawPack(jurisdiction={"state": "XX"}, rules=[rule], coverage="full"))
    assert pol.mode == "one_to_one" and pol.premium_status == "owed" and pol.sentences == []
    assert policy(cfg, None).premium_status == "not_applicable"


def test_seattle_one_to_one_plan_is_sent_one_to_one_and_owed(settings, fake_engine):
    c, sid, cfg = _client_in(settings, "WA", "seattle")
    try:
        r = c.post(f"/api/stores/{sid}/fix", json={"callouts": [], "day": 5, "now": 364, "outreach_mode": "one_to_one"})
        plan = r.json()
        assert plan["outreach_mode"] == "one_to_one"
        c.post(f"/api/stores/{sid}/outreach/start", json={"plan_id": plan["plan_id"]})
        st = _wait(c, sid, lambda s: s.current_rank == 1)
        assert st.mode == "one_to_one" and st.premium["status"] == "owed" and len(st.messages) == 1
        assert "mass communication" not in st.messages[0].body
        assert [b["employee_id"] for b in st.premium["by_employee"]] == _cashiers(cfg)
    finally:
        c.__exit__(None, None, None)


def test_group_wave_keeps_both_when_shifts_differ(settings, fake_engine, monkeypatch):
    """Two people offered DIFFERENT shifts in one group wave both say YES: both are booked, nobody gets 'filled'."""
    times = {}

    def fix_day(req, time_limit_s=8):
        fake_engine.append(req)
        cash = _cashiers(req.config)
        times.setdefault(cash[0], (600, 840))
        times.setdefault(cash[1], (900, 1140))
        booked = {s.employee_id for s in req.schedule.shifts if s.id.startswith("s_")}
        queue = []
        for i, e in enumerate(x for x in cash if x not in booked and x not in req.declined_employee_ids):
            a, b = times[e]
            sh = Shift(id=f"s_{e}", employee_id=e, day=5, start=a, end=b,
                       segments=[RoleSegment(role_id="cashier", start=a, end=b)])
            queue.append(OutreachCandidate(rank=i + 1, employee_id=e, proposed_shift=sh, added_cost_dollars=64.0,
                                           est_accept_prob=0.5, why="trained"))
        s = req.schedule
        return FixPlan(actions=[], outreach_queue=queue, schedule_if_all_accept=s, schedule_if_none_accept=s,
                       coverage_before_pct=50.0, coverage_after_best_pct=100.0, coverage_after_worst_pct=50.0,
                       outreach_mode=req.outreach_mode or "one_to_one")
    monkeypatch.setattr(integrations, "fix_day", fix_day)
    settings.mock_autoreply = "off"
    c, sid, cfg = _client_in(settings, "WA", "seattle")
    try:
        rank1, rank2 = _cashiers(cfg)
        _start(c, sid)
        st = _wait(c, sid, lambda s: len(s.messages) >= 2)
        assert st.mode == "group_offer" and {m.to_employee_id for m in st.messages} == {rank1, rank2}
        phones = {m.to_employee_id: m.to_phone for m in st.messages}
        c.post("/api/sms/mock-reply", json={"from_phone": phones[rank1], "body": "YES"})
        st = _wait(c, sid, lambda s: rank1 in s.accepted_employee_ids)
        assert st.status == "texting" and st.waiting_employee_ids == [rank2]  # rank2's shift is still open
        c.post("/api/sms/mock-reply", json={"from_phone": phones[rank2], "body": "yes I can"})
        st = _wait(c, sid, lambda s: s.status == "filled")
        assert sorted(st.accepted_employee_ids) == sorted([rank1, rank2])
        assert not any("filled" in m.body for m in st.messages if getattr(m, "to_employee_id", None))
        assert sorted((s.employee_id, s.start) for s in st.schedule.shifts) == sorted([(rank1, 600), (rank2, 900)])
    finally:
        c.__exit__(None, None, None)


def test_group_offer_with_one_candidate_is_not_called_mass(settings, fake_engine, monkeypatch):
    real = integrations.fix_day

    def one(req, time_limit_s=8):
        plan = real(req, time_limit_s)
        return plan.model_copy(update={"outreach_queue": plan.outreach_queue[:1]})
    monkeypatch.setattr(integrations, "fix_day", one)
    c, sid, cfg = _client_in(settings, "WA", "seattle")
    try:
        _start(c, sid)
        st = _wait(c, sid, lambda s: any(getattr(m, "to_employee_id", None) for m in s.messages))
        offer = next(m for m in st.messages if getattr(m, "to_employee_id", None))
        assert "mass communication" not in offer.body and "voluntary" in offer.body
        assert st.premium["status"] == "owed"
    finally:
        c.__exit__(None, None, None)


def test_moved_shift_is_reoffered_and_old_yes_ignored(settings, fake_engine, monkeypatch):
    def fix_day(req, time_limit_s=8):
        fake_engine.append(req)
        cash = _cashiers(req.config)
        booked = {s.employee_id for s in req.schedule.shifts if s.id.startswith("s_")}
        start = 960 if booked else 900  # once someone is booked, the engine moves the other shift by 1 h
        queue = []
        for i, e in enumerate(x for x in cash if x not in booked and x not in req.declined_employee_ids):
            a, b = (600, 840) if e == cash[0] else (start, start + 240)
            sh = Shift(id=f"s_{e}", employee_id=e, day=5, start=a, end=b,
                       segments=[RoleSegment(role_id="cashier", start=a, end=b)])
            queue.append(OutreachCandidate(rank=i + 1, employee_id=e, proposed_shift=sh, added_cost_dollars=64.0,
                                           est_accept_prob=0.5, why="trained"))
        s = req.schedule
        return FixPlan(actions=[], outreach_queue=queue, schedule_if_all_accept=s, schedule_if_none_accept=s,
                       coverage_before_pct=50.0, coverage_after_best_pct=100.0, coverage_after_worst_pct=50.0,
                       outreach_mode=req.outreach_mode or "one_to_one")
    monkeypatch.setattr(integrations, "fix_day", fix_day)
    from shiftwright_api.outreach import OutreachManager
    slow_commit = OutreachManager._commit_shift

    def commit(self, *a):
        time.sleep(0.3)  # rank 2's YES (to the old times) arrives while rank 1's accept is being booked
        return slow_commit(self, *a)
    monkeypatch.setattr(OutreachManager, "_commit_shift", commit)
    c, sid, cfg = _client_in(settings, "WA", "seattle")
    try:
        rank1, rank2 = _cashiers(cfg)
        _start(c, sid)
        st = _wait(c, sid, lambda s: len(s.messages) >= 2)
        phones = {m.to_employee_id: m.to_phone for m in st.messages}
        c.post("/api/sms/mock-reply", json={"from_phone": phones[rank1], "body": "YES"})
        time.sleep(0.05)
        c.post("/api/sms/mock-reply", json={"from_phone": phones[rank2], "body": "YES"})  # to the 3 pm offer
        st = _wait(c, sid, lambda s: any(m.body.startswith("Update:") for m in s.messages))
        assert st.status == "texting" and rank2 not in st.accepted_employee_ids and st.waiting_employee_ids == [rank2], [(getattr(m, "to_employee_id", None) or m.from_phone, m.body[:40]) for m in st.messages]
        upd = next(m for m in st.messages if m.body.startswith("Update:"))
        assert upd.to_employee_id == rank2 and "4 pm-8 pm" in upd.body
        c.post("/api/sms/mock-reply", json={"from_phone": phones[rank2], "body": "yes"})
        st = _wait(c, sid, lambda s: s.status == "filled")
        assert sorted((s.employee_id, s.start) for s in st.schedule.shifts) == sorted([(rank1, 600), (rank2, 960)])
    finally:
        c.__exit__(None, None, None)


def test_fix_apply_saves_none_accept_schedule_with_recomputed_metrics(oclient, fake_engine, monkeypatch):
    c, sid, cfg = oclient
    real = integrations.fix_day
    marker = Shift(id="a_extend", employee_id=_cashiers(cfg)[0], day=5, start=600, end=840,
                   segments=[RoleSegment(role_id="cashier", start=600, end=840)])

    def fix_day(req, time_limit_s=8):
        plan = real(req, time_limit_s)
        none = plan.schedule_if_none_accept.model_copy(deep=True)
        none.shifts = [s for s in none.shifts if s.employee_id != "e9"] + [marker]
        return plan.model_copy(update={"schedule_if_none_accept": none})
    monkeypatch.setattr(integrations, "fix_day", fix_day)
    plan = c.post(f"/api/stores/{sid}/fix", json={"callouts": [], "day": 5, "now": 364}).json()
    body = c.post(f"/api/stores/{sid}/fix/apply", json={"plan_id": plan["plan_id"]}).json()
    assert [s["id"] for s in body["schedule"]["shifts"]] == ["a_extend"]
    assert body["schedule"]["metrics"]["total_hours"] == 4.0 and body["validation"]["passed"]
    st = OutreachState.model_validate(c.post(f"/api/stores/{sid}/outreach/start", json={"plan_id": plan["plan_id"]}).json())
    assert [s.id for s in st.schedule.shifts] == ["a_extend"]  # outreach builds on the applied plan
    st = _wait(c, sid, lambda s: s.current_rank == 1)
    c.post("/api/sms/mock-reply", json={"from_phone": st.messages[-1].to_phone, "body": "no"})
    _wait(c, sid, lambda s: len(s.messages) >= 3)
    # re-fixes plan against the posted schedule (+ booked call-ins), not the one with actions already applied
    assert "a_extend" not in {x.id for x in fake_engine[-1].schedule.shifts}
