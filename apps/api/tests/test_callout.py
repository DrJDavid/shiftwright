"""Call-outs by message: the employee page (or a text) says "sick", and repair + offers start on their own."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api_helpers import tiny_config
from shiftwright_api import callout
from shiftwright_api.agent.llm import FakeLLM, LLMResponse
from shiftwright_api.models import OutreachState
from shiftwright_contracts.models import RoleSegment, Shift, ValidationReport

from test_outreach import _wait, fake_engine, oclient  # noqa: F401  (fixtures)


def _shift(emp, day, start=600, end=840, sid=None):
    return Shift(id=sid or f"w_{emp}_{day}", employee_id=emp, day=day, start=start, end=end,
                 segments=[RoleSegment(role_id="cashier", start=start, end=end)])


def _post_week(c, sid, shifts):
    """Put a posted schedule with these shifts in place of the stub's empty one."""
    db = c.app.state.db
    sched, _ = db.latest_schedule(sid)
    sched = sched.model_copy(update={"shifts": shifts})
    db.save_schedule(sid, sched, ValidationReport(passed=True, hard_count=0, violations=[],
                                                  recomputed_metrics=sched.metrics))


def _caller(cfg):
    return next(e for e in sorted(cfg.employees, key=lambda e: e.id) if e.phone)


def test_sick_message_starts_coverage_on_its_own(oclient):
    c, sid, cfg = oclient
    me = _caller(cfg)
    _post_week(c, sid, [_shift(me.id, 5)])
    r = c.post("/api/sms/mock-reply", json={"from_phone": me.phone, "store_id": sid,
                                            "body": "so sorry, I'm sick and can't make it Saturday"})
    assert r.status_code == 200, r.text
    co = r.json()["callout"]
    assert co["status"] == "covering" and co["employee_id"] == me.id and co["shift"]["day"] == 5 and co["plan_id"]
    st = _wait(c, sid, lambda s: s.status == "texting" and len(s.messages) >= 3)
    bodies = [m.body for m in st.messages]
    assert bodies[0].startswith("so sorry") and "feel better" in bodies[1]  # their text, then our reply
    latest = c.get(f"/api/stores/{sid}/callout").json()
    assert latest["callout"]["id"] == co["id"] and latest["plan"]["plan_id"] == co["plan_id"]


def test_other_messages_are_not_call_outs(oclient):
    c, sid, cfg = oclient
    me = _caller(cfg)
    _post_week(c, sid, [_shift(me.id, 5)])
    co = c.post("/api/sms/mock-reply", json={"from_phone": me.phone, "store_id": sid,
                                             "body": "what time do I start saturday?"}).json()["callout"]
    assert co["status"] == "not_a_callout" and co["plan_id"] is None
    assert OutreachState.model_validate(c.get(f"/api/stores/{sid}/outreach").json()).status == "idle"


def test_no_shift_that_day_asks_which_one(oclient):
    c, sid, cfg = oclient
    me = _caller(cfg)
    _post_week(c, sid, [_shift(me.id, 2)])
    co = c.post("/api/sms/mock-reply", json={"from_phone": me.phone, "store_id": sid,
                                             "body": "I'm sick, can't come in Saturday"}).json()["callout"]
    assert co["status"] == "unclear" and co["plan_id"] is None


def test_page_must_name_a_store(oclient):
    c, sid, cfg = oclient
    me = _caller(cfg)
    _post_week(c, sid, [_shift(me.id, 5)])
    assert c.post("/api/sms/mock-reply", json={"from_phone": me.phone, "body": "sick"}).json()["callout"] is None


# ---------------------------------------------------------------- reading the message
def test_days_and_upcoming_shifts():
    assert callout.day_named("can't come in tomorrow", today=6) == 0
    assert callout.day_named("sick today", today=3) == 3
    assert callout.day_named("out on Tues", today=0) == 1
    assert callout.day_named("i'm sick", today=0) is None
    a, b, cc = _shift("e1", 1), _shift("e1", 4), _shift("e1", 5, 300, 400)
    assert [s.day for s in callout.upcoming([a, b, cc], today=5, now=500)] == [1, 4, 5]  # today's is over: wraps
    assert [s.day for s in callout.upcoming([a, b, cc], today=5, now=310)] == [5, 1, 4]


def test_llm_reads_against_their_shifts_and_bad_answers_fall_back():
    cfg = tiny_config()
    shifts = [_shift("e1", 5), _shift("e1", 6)]
    llm = FakeLLM([LLMResponse(content='{"callout": true, "shift": 1}')])
    got = asyncio.run(callout.read_message(llm, cfg, "kid's sick, can't do my sunday", shifts, today=5))
    assert got["callout"] and got["shift"].day == 6 and got["how"] == "llm"
    llm = FakeLLM([LLMResponse(content='{"callout": true, "shift": 9}')])  # not in the list: keywords pick
    got = asyncio.run(callout.read_message(llm, cfg, "sick, can't make it sunday", shifts, today=5))
    assert got["shift"].day == 6
    got = asyncio.run(callout.read_message(FakeLLM([]), cfg, "running 5 min late", shifts, today=5))
    assert not got["callout"] and got["how"] == "keywords"


def test_local_now_uses_the_store_timezone():
    cfg = tiny_config()
    cfg.store.timezone = "America/Chicago"
    # Sat 2026-11-07 22:00 UTC = 16:00 in Chicago
    assert callout.local_now(cfg, datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc)) == (5, 960)
