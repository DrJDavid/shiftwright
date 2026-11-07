"""Shared fixtures for WS6 tests.

`tiny_config()` is a hand-built stand-in until WS4's `tiny_store.json` lands on main;
the tests switch to the fixture automatically when it exists.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from shiftwright_contracts.models import StoreConfig

REPO = Path(__file__).resolve().parents[3]
TINY_FIXTURE = REPO / "packages/scenarios/fixtures/tiny_store.json"


def tiny_config() -> StoreConfig:
    if TINY_FIXTURE.exists():
        return StoreConfig.model_validate(json.loads(TINY_FIXTURE.read_text()))
    return StoreConfig.model_validate(
        {
            "store": {
                "id": "tiny",
                "name": "Tiny Store",
                "jurisdiction": {"state": "TX", "city": "austin"},
                "slot_minutes": 30,
                "week_start": "2026-11-09",
                "hours": [{"day": 0, "open": 480, "close": 1200}, {"day": 5, "open": 480, "close": 1200}],
            },
            "departments": [{"id": "front_of_store", "name": "Front of Store"}],
            "roles": [
                {"id": "cashier", "department_id": "front_of_store", "name": "Cashier", "gap_penalty_per_hour": 30},
                {"id": "leader_on_duty", "department_id": "front_of_store", "name": "Leader on Duty", "gap_penalty_per_hour": 100},
            ],
            "employees": [
                {
                    "id": f"e{i}",
                    "name": n,
                    "phone": f"+1555000000{i}",
                    "age": 25,
                    "home_department_id": "front_of_store",
                    "trained_role_ids": roles,
                    "status": "part_time",
                    "wage_per_hour": 16.0,
                    "hire_date": "2024-01-01",
                }
                for i, (n, roles) in enumerate(
                    [("Ana", ["cashier"]), ("Ben", ["cashier", "leader_on_duty"]), ("Cy", ["leader_on_duty"])]
                )
            ],
            "demand": [
                {"id": "d0", "role_id": "cashier", "day": 0, "start": 480, "end": 1200, "headcount": 1, "source": "corporate"},
                {"id": "d1", "role_id": "leader_on_duty", "day": 0, "start": 480, "end": 1200, "headcount": 1, "source": "corporate"},
                {"id": "d5", "role_id": "cashier", "day": 5, "start": 480, "end": 1200, "headcount": 1, "source": "corporate"},
            ],
            "budget": {"weekly_hours_cap": 60},
        }
    )


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        if ev:
            events.append((ev, data))
    return events


def signup(client, email: str = "leader@example.com", password: str = "correct horse",
           name: str = "Store Leader") -> dict:
    """Create an account; the client keeps its `sw_session` cookie for later requests."""
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "name": name})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def make_store(client, **kw) -> dict:
    """Signs the client up first if it has no session yet (auth is on in tests)."""
    if not client.cookies.get("sw_session") and client.get("/api/auth/me").status_code == 401:
        signup(client)
    body = {"name": "Store #0417", "jurisdiction": {"state": "TX", "city": "austin"}, **kw}
    r = client.post("/api/stores", json=body)
    assert r.status_code == 200, r.text
    return r.json()
