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


def test_priority_levels_are_priced_above_pay():
    from shiftwright_api import priorities as P
    d = {"roles": [{"id": "barista", "gap_penalty_per_hour": 0.0}, {"id": "lead", "gap_penalty_per_hour": 7.0}],
         "employees": [{"wage_per_hour": 15, "trained_role_ids": ["barista"]},
                       {"wage_per_hour": 18, "trained_role_ids": ["barista", "lead"]}]}
    P.apply(d, {"barista": "nice_to_have"})
    assert d["roles"][0]["gap_penalty_per_hour"] == 20.0      # ceil(1.1 x 18): still above every barista's pay
    assert d["roles"][1]["gap_penalty_per_hour"] == 7.0       # no level: custom value untouched
    for lvl in P.LEVELS:
        assert P.penalty(lvl, 18) > 18
    assert P.penalty("must_cover", 18) > P.penalty("important", 18) > P.penalty("nice_to_have", 18)


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
        assert saved.gap_penalty_per_hour == P.penalty("must_cover", P.FALLBACK_WAGE)


def test_readiness_flags_priority_below_pay():
    import json
    from pathlib import Path

    from shiftwright_api.readiness import compute
    from shiftwright_contracts.models import StoreConfig

    raw = json.loads((Path(__file__).parents[3] / "packages/scenarios/fixtures/tiny_store.json").read_text())
    cfg = StoreConfig(**raw)
    role = next(r for r in cfg.roles if any(r.id in e.trained_role_ids for e in cfg.employees)
                and any(d.role_id == r.id and d.headcount > 0 for d in cfg.demand))
    role.gap_penalty_per_hour = 1.0  # below every wage
    check = next(c for c in compute(cfg).checks if c.id == "priorities")
    assert check.ok is False and "below what their staff earn" in check.detail
