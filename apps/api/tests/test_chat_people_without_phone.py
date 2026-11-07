"""People entered in chat don't need a phone; outreach skips anyone without one."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from shiftwright_api.agent import tools as T
from shiftwright_api.outreach import OutreachManager


def test_upsert_employee_schema_requires_only_what_the_tool_cannot_fill():
    tool = next(t for t in T.TOOLS if t.name == "upsert_employee")
    req = tool.parameters["properties"]["employee"]["required"]
    assert set(req) == {"id", "name", "age", "wage_per_hour", "trained_role_ids"}
    assert "phone" not in req and "hire_date" not in req


def test_send_skips_employee_without_phone():
    notes: list[str] = []
    sent: list[str] = []

    class Msgr:
        async def send(self, emp, body, outreach_rank=None):  # pragma: no cover - must not be called
            sent.append(emp.name)

    o = OutreachManager.__new__(OutreachManager)
    o.messenger = Msgr()
    o._note = lambda run, text: notes.append(text)
    emp = SimpleNamespace(name="Gus", phone="")
    ok = asyncio.run(o._send(SimpleNamespace(store_id="s1"), emp, "Can you work?", 1))
    assert ok is False and sent == []
    assert notes and "no phone number" in notes[0]


def test_priority_levels_are_ordered_tiers():
    from shiftwright_api import priorities as P
    d = {"roles": [{"id": "barista", "gap_penalty_per_hour": 0.0}, {"id": "lead", "gap_penalty_per_hour": 7.0}],
         "employees": [{"wage_per_hour": 15, "trained_role_ids": ["barista"]},
                       {"wage_per_hour": 18, "trained_role_ids": ["barista", "lead"]}]}
    P.apply(d, {"barista": "nice_to_have"})
    assert d["roles"][0]["gap_penalty_per_hour"] == 100.0     # the Nice to have tier (C3: a rank, not a price)
    assert d["roles"][1]["gap_penalty_per_hour"] == 7.0       # no level: custom value untouched
    assert P.penalty("must_cover") > P.penalty("important") > P.penalty("nice_to_have")


def test_roles_card_saves_levels_and_reprices(tmp_path):
    from fastapi.testclient import TestClient
    from api_helpers import make_store
    from shiftwright_api import priorities as P
    from shiftwright_api.main import create_app
    from shiftwright_api.settings import Settings

    s = Settings.from_env()
    s.database_url = f"sqlite:///{tmp_path}/t.db"
    s.openrouter_api_key = ""
    with TestClient(create_app(settings=s)) as c:
        sid = make_store(c, template="empty")["store"]["id"]
        app_db = c.app.state.db
        ctx = T.ToolContext(db=app_db, store_id=sid)
        card = T.ask_roles(ctx, {"departments": [{"id": "cafe", "name": "Cafe"}],
                                 "roles": [{"id": "barista", "department_id": "cafe", "name": "Barista"}]})
        role = next(r for r in card.props["roles"] if r["id"] == "barista")
        assert role["priority"] == "important" and role["gap_penalty_per_hour"] > 0
        res = card.apply({"departments": card.props["departments"],
                          "roles": [{**role, "priority": "must_cover"}]})
        assert res.content.get("ok"), res.content
        assert P.load(app_db, sid) == {"barista": "must_cover"}
        saved = app_db.get_config(sid).roles[0]
        assert saved.gap_penalty_per_hour == P.penalty("must_cover")


def test_rule_card_resolves_short_names_and_defaults_preference_weight(tmp_path):
    import json
    from pathlib import Path

    from fastapi.testclient import TestClient
    from api_helpers import make_store
    from shiftwright_api.main import create_app
    from shiftwright_api.settings import Settings

    s = Settings.from_env()
    s.database_url = f"sqlite:///{tmp_path}/t.db"
    s.openrouter_api_key = ""
    with TestClient(create_app(settings=s)) as c:
        sid = make_store(c, template="tiny")["store"]["id"]
        db = c.app.state.db
        cfg = db.get_config(sid)
        a, b = cfg.employees[0], cfg.employees[1]
        short = lambda e: f"{e.name.split()[0]} {e.name.split()[-1][0]}."  # "Jules C."
        ctx = T.ToolContext(db=db, store_id=sid)
        card = T.propose_rule(ctx, {"constraint": {"kind": "not_together", "params": {"employee_ids": [short(a), short(b)]},
                                                   "strength": "soft"},
                                    "plain_text": f"{short(a)} and {short(b)} can't be on the same shift"})
        assert card.props["constraint"]["params"]["employee_ids"] == [a.id, b.id]
        res = card.apply({"decision": "soft"})  # no weight given: a preference gets the default, never an error
        assert res.content.get("ok"), res.content
        saved = next(x for x in db.get_config(sid).constraints if x.kind.value == "not_together" and x.status.value == "confirmed")
        assert saved.weight_dollars == T.DEFAULT_SOFT_WEIGHT


def test_incomplete_rules_are_refused_and_never_crash_a_build(tmp_path):
    from fastapi.testclient import TestClient
    from api_helpers import make_store
    from shiftwright_api import rules
    from shiftwright_api.main import create_app
    from shiftwright_api.settings import Settings

    assert "minutes" in rules.problem("min_shift_length", {})
    assert rules.problem("min_shift_length", {"minutes": 240}) is None

    s = Settings.from_env()
    s.database_url = f"sqlite:///{tmp_path}/t.db"
    s.openrouter_api_key = ""
    with TestClient(create_app(settings=s)) as c:
        sid = make_store(c, template="tiny")["store"]["id"]
        db = c.app.state.db
        ctx = T.ToolContext(db=db, store_id=sid)
        out = T.propose_rule(ctx, {"constraint": {"kind": "min_shift_length", "params": {}, "strength": "hard"},
                                   "plain_text": "Nobody comes in for less than 4 hours"})
        assert isinstance(out, T.ToolResult) and "minutes" in out.content["error"]
        # an incomplete rule that got in some other way is set aside, and the week still builds
        cfg = c.get(f"/api/stores/{sid}/config").json()
        cfg["constraints"].append({"id": "c_bad", "kind": "min_shift_length", "params": {}, "strength": "hard",
                                   "status": "confirmed", "source": "leader"})
        assert c.put(f"/api/stores/{sid}/config", json=cfg).status_code == 200
        r = c.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 10})
        assert r.status_code == 200, r.text[:300]
        sched = r.json()["schedule"]
        assert sched["shifts"] and any("c_bad" in n for n in sched["solver_stats"]["notes"])
