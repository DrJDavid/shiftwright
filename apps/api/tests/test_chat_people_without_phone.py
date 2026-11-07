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


def test_new_roles_get_a_priority_worth_covering():
    assert T._with_default_priority({"id": "barista"})["gap_penalty_per_hour"] == T.DEFAULT_GAP_PENALTY_PER_HOUR
    assert T._with_default_priority({"id": "barista", "gap_penalty_per_hour": 0})["gap_penalty_per_hour"] == 50.0
    assert T._with_default_priority({"id": "barista", "gap_penalty_per_hour": 80})["gap_penalty_per_hour"] == 80


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
    assert check.ok is False and "less than paying" in check.detail
