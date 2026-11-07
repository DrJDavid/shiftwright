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


class TemplateUnavailable(LookupError):
    pass


def is_fixture(template: str) -> bool:
    return template in FIXTURE_TEMPLATES or template.startswith("demo_")


def from_fixture(template: str, store_id: str | None = None) -> StoreConfig:
    """WS4 fixture store as-is, under a new store id. `demo_<locality>` (e.g. demo_chicago) asks WS4's
    `load_demo_store(locality=...)`, or reads fixtures/demo_store_<locality>.json, when present."""
    import shiftwright_scenarios

    if template in FIXTURE_TEMPLATES:
        cfg = getattr(shiftwright_scenarios, FIXTURE_TEMPLATES[template])()
    else:
        locality = template[len("demo_"):]
        cfg = None
        try:
            cfg = shiftwright_scenarios.load_demo_store(locality=locality)
        except TypeError:  # loader without locality support yet
            pass
        except (FileNotFoundError, KeyError, ValueError) as e:
            raise TemplateUnavailable(f"No demo store for {locality!r}: {e}") from e
        if cfg is None:
            path = getattr(shiftwright_scenarios, "FIXTURES_DIR", None)
            f = path / f"demo_store_{locality}.json" if path else None
            if not (f and f.exists()):
                raise TemplateUnavailable(f"No demo store for {locality!r} yet.")
            cfg = StoreConfig.model_validate_json(f.read_text())
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


KNOWN_LOCALITIES = ["chicago", "seattle", "sf"]
_LABELS = {"empty": "Empty store (start from scratch)", "bigbox_small": "Big-box store, small (roles only)",
           "bigbox_mid": "Big-box store, mid-size (roles only)"}


def available() -> list[dict]:
    """GET /api/templates: structure templates + every fixture store that loads on this server."""
    out = [{"id": t, "label": label, "jurisdiction": None} for t, label in _LABELS.items()]
    ids = ["demo", "tiny"] + [f"demo_{loc}" for loc in KNOWN_LOCALITIES]
    try:
        import shiftwright_scenarios
        fx = getattr(shiftwright_scenarios, "FIXTURES_DIR", None)
        if fx:
            ids += sorted(f"demo_{p.stem[len('demo_store_'):]}" for p in fx.glob("demo_store_*.json"))
    except ImportError:
        return out
    for t in dict.fromkeys(ids):
        try:
            cfg = from_fixture(t)
        except Exception:  # noqa: BLE001 - not available on this server
            continue
        out.append({"id": t, "label": f"{cfg.store.name} ({len(cfg.employees)} staff)",
                    "jurisdiction": cfg.store.jurisdiction.model_dump(mode="json")})
    return out
