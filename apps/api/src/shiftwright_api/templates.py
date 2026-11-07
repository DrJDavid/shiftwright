"""Store templates for POST /api/stores. Everything here is a reviewable default.

Templates only provide structure (departments, roles, generic store hours). They carry no
employees, no demand and a zero hours cap, so readiness stays red until the leader fills
those in. Roles in the contract have no `source` field, so every template role's
description says "Template default — review." and the store hours are marked in the
readiness detail.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from shiftwright_contracts.models import Budget, Department, Jurisdiction, Role, Store, StoreConfig

DEFAULT_NOTE = "Template default — review."

# (department_id, department name, [(role_id, role name, gap_penalty_per_hour, min_age)])
_SMALL = [
    ("front_of_store", "Front of Store", [
        ("guest_service_desk", "Guest Service Desk", 40, 0),
        ("cashier", "Cashier", 30, 0),
        ("cart_attendant", "Cart Attendant", 10, 0),
        ("drive_up", "Drive Up", 25, 0),
    ]),
    ("general_merchandise", "General Merchandise", [
        ("softlines", "Softlines", 12, 0),
        ("hardlines", "Hardlines", 12, 0),
        ("fitting_room", "Fitting Room", 15, 0),
    ]),
    ("grocery", "Grocery", [("grocery_stock", "Grocery Stock", 15, 0)]),
    ("leadership", "Leadership", [("leader_on_duty", "Leader on Duty", 200, 18)]),
]
_MID_EXTRA = [
    ("fulfillment", "Fulfillment", [("order_picker", "Order Picker", 25, 0)]),
    ("asset_protection", "Asset Protection", [("ap_specialist", "AP Specialist", 20, 0)]),
    ("receiving", "Receiving", [
        ("truck_unload", "Truck Unload", 35, 0),
        ("backroom", "Backroom", 15, 0),
        ("pit_operator", "PIT Operator", 35, 18),
    ]),
]
_ROLE_TAGS = {"pit_operator": ["powered_industrial_truck"]}


def next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def new_store_id() -> str:
    return "st_" + uuid.uuid4().hex[:10]


FIXTURE_TEMPLATES = {"demo": "load_demo_store", "tiny": "load_tiny_store"}


def from_fixture(template: str, store_id: str | None = None) -> StoreConfig:
    """WS4 fixture store (demo_store.json / tiny_store.json) as-is, under a new store id."""
    import shiftwright_scenarios

    cfg = getattr(shiftwright_scenarios, FIXTURE_TEMPLATES[template])()
    cfg.store.id = store_id or new_store_id()
    cfg.config_version = 1
    return cfg


def build(template: str, name: str, jurisdiction: Jurisdiction, store_id: str | None = None) -> StoreConfig:
    spec = {"empty": [], "bigbox_small": _SMALL, "bigbox_mid": _SMALL + _MID_EXTRA}[template]
    departments = [Department(id=d, name=n) for d, n, _ in spec]
    roles = [
        Role(id=r, department_id=d, name=rn, gap_penalty_per_hour=pen, min_age=age, description=DEFAULT_NOTE)
        for d, _, rs in spec
        for r, rn, pen, age in rs
    ]
    hours = [] if template == "empty" else [dict(day=d, open=8 * 60, close=22 * 60) for d in range(7)]
    store = Store(
        id=store_id or new_store_id(),
        name=name,
        jurisdiction=jurisdiction,
        week_start=next_monday(),
        hours=hours,
    )
    role_ids = {r.id for r in roles}
    return StoreConfig(
        store=store,
        departments=departments,
        roles=roles,
        role_tags={k: v for k, v in _ROLE_TAGS.items() if k in role_ids},
        employees=[],
        demand=[],
        budget=Budget(weekly_hours_cap=0),
    )
