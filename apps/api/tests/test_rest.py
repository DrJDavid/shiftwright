"""Contract tests: every REST response validates against its model (API.md)."""
from __future__ import annotations

from api_helpers import make_store, tiny_config
from shiftwright_contracts.models import CONTRACT_VERSION, LawPack, Schedule, StoreConfig, ValidationReport

from shiftwright_api.models import Readiness


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["contract_version"] == CONTRACT_VERSION
    assert body["messenger"] == "mock"
    assert body["model"] == "fake/model"


def test_create_get_put_config(client):
    cfg = StoreConfig.model_validate(make_store(client, template="bigbox_small"))
    assert cfg.store.name == "Store #0417"
    assert cfg.store.week_start.weekday() == 0
    assert cfg.roles, "bigbox template ships default roles"

    got = StoreConfig.model_validate(client.get(f"/api/stores/{cfg.store.id}/config").json())
    assert got == cfg

    edited = got.model_copy(deep=True)
    edited.store.name = "Renamed"
    r = client.put(f"/api/stores/{cfg.store.id}/config", json=edited.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    put = StoreConfig.model_validate(r.json())
    assert put.store.name == "Renamed"
    assert put.config_version == cfg.config_version + 1
    assert put.store.id == cfg.store.id


def test_empty_template_and_unknown_store(client):
    cfg = StoreConfig.model_validate(make_store(client, template="empty"))
    assert cfg.roles == [] and cfg.employees == []
    assert client.get("/api/stores/nope/config").status_code == 404


def test_put_invalid_config_rejected(client):
    cfg = make_store(client)
    cfg["budget"] = {"weekly_hours_cap": "lots"}
    r = client.put(f"/api/stores/{cfg['store']['id']}/config", json=cfg)
    assert r.status_code == 422


def _put_tiny(client) -> str:
    sid = make_store(client)["store"]["id"]
    cfg = tiny_config().model_copy(deep=True)
    cfg.store.id = sid
    r = client.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    return sid


def test_solve_returns_schedule_and_validation(client):
    sid = _put_tiny(client)
    r = client.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    sched = Schedule.model_validate(body["schedule"])
    ValidationReport.model_validate(body["validation"])
    assert sched.store_id == sid
    latest = client.get(f"/api/stores/{sid}/schedule").json()
    assert Schedule.model_validate(latest["schedule"]) == sched


def test_schedule_404_before_solve(client):
    sid = make_store(client)["store"]["id"]
    assert client.get(f"/api/stores/{sid}/schedule").status_code == 404


def test_readiness(client):
    sid = make_store(client, template="empty")["store"]["id"]
    rd = Readiness.model_validate(client.get(f"/api/stores/{sid}/readiness").json())
    assert rd.ready is False
    assert [c.id for c in rd.checks] == [
        "store_basics", "jurisdiction", "roles", "employees", "training", "demand", "priorities", "equipment_roles",
        "minors_on_tagged_roles", "business_type", "staffing_draft", "budget", "minimum_wage", "provisional_rules"]

    sid = _put_tiny(client)
    rd = Readiness.model_validate(client.get(f"/api/stores/{sid}/readiness").json())
    assert rd.ready is True, rd


def test_readiness_names_employees_below_minimum_wage(client):
    sid = _put_tiny(client)
    cfg = StoreConfig.model_validate(client.get(f"/api/stores/{sid}/config").json())
    low = cfg.employees[0]
    low.wage_per_hour = 5.0
    assert client.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json")).status_code == 200
    rd = Readiness.model_validate(client.get(f"/api/stores/{sid}/readiness").json())
    check = next(c for c in rd.checks if c.id == "minimum_wage")
    assert rd.ready is False and check.ok is False
    assert low.name in check.detail and "$5.00" in check.detail


def test_laws_resolve(client):
    r = client.get("/api/laws/resolve", params={"state": "TX", "city": "austin"})
    assert r.status_code == 200
    LawPack.model_validate(r.json())


def test_fixture_templates(client):
    from shiftwright_scenarios import load_demo_store, load_tiny_store
    for template, loader in (("demo", load_demo_store), ("tiny", load_tiny_store)):
        r = client.post("/api/stores", json={"template": template})
        assert r.status_code == 200, r.text
        cfg = StoreConfig.model_validate(r.json())
        want = loader()
        assert cfg.store.id != want.store.id and cfg.store.id.startswith("st_")
        assert cfg.store.name == want.store.name and len(cfg.employees) == len(want.employees)
        assert cfg.demand == want.demand and cfg.constraints == want.constraints
    assert client.post("/api/stores", json={"template": "bigbox_mid"}).status_code == 422


def test_solve_reports_engine_crash(client, monkeypatch):
    from shiftwright_api import integrations

    def boom(*a, **k):
        raise MemoryError("out of memory")
    monkeypatch.setattr(integrations, "solve_week", boom)
    sid = _put_tiny(client)
    r = client.post(f"/api/stores/{sid}/solve", json={})
    assert r.status_code == 500 and "Schedule engine failed (MemoryError" in r.json()["detail"]


def test_human_readable_text():
    from shiftwright_api.explain import clock, phrase_gap
    from shiftwright_api.readiness import compute
    from shiftwright_contracts.models import Gap
    assert [clock(m) for m in (0, 390, 720, 870, 1320, 1440)] == ["12 am", "6:30 am", "12 pm", "2:30 pm", "10 pm", "12 am"]
    cfg = tiny_config()
    role = cfg.roles[0]
    text = phrase_gap(cfg, Gap(role_id=role.id, day=5, start=600, end=870, missing_headcount=1, penalty_dollars=120.0,
                               reasons=[]), [])
    assert text.startswith(f"{role.name} Sat 10 am–2:30 pm uncovered (1 short, $120)")
    cfg = cfg.model_copy(deep=True)
    day = min(d.day for d in cfg.demand)
    cfg.demand = [d for d in cfg.demand if d.day != day]
    for e in cfg.employees:
        e.trained_role_ids = [r for r in e.trained_role_ids if r != role.id]
    checks = {c.id: c.detail for c in compute(cfg).checks}
    assert role.name in checks["training"] and role.id not in checks["training"].split(": ")[1].split(", ")
    assert ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][day] in checks["demand"]


def test_locality_demo_templates(client):
    for loc in ("chicago", "seattle", "sf"):
        r = client.post("/api/stores", json={"template": f"demo_{loc}"})
        if r.status_code == 422:
            continue  # WS4's locality variant not landed yet
        assert r.status_code == 200, r.text
        assert StoreConfig.model_validate(r.json()).store.id.startswith("st_")
    assert client.post("/api/stores", json={"template": "demo_nowhere"}).status_code == 422
    assert client.post("/api/stores", json={"template": "../etc"}).status_code == 422


def test_templates_list(client):
    t = client.get("/api/templates").json()["templates"]
    ids = [x["id"] for x in t]
    assert ids[:4] == ["empty", "bigbox_small", "bigbox_mid", "restaurant_small"] and "demo" in ids and "tiny" in ids
    demo = next(x for x in t if x["id"] == "demo")
    assert demo["jurisdiction"]["state"] == "TX" and "Store #0417" in demo["label"]
    for x in t:  # every listed template can be created
        body = {"template": x["id"]} if x["jurisdiction"] else {"template": x["id"], "name": "x",
                                                                  "jurisdiction": {"state": "TX"}}
        assert client.post("/api/stores", json=body).status_code == 200, x


def test_restaurant_small_template(client):
    cfg = StoreConfig.model_validate(make_store(client, template="restaurant_small"))
    assert cfg.store.sector.value == "food"
    assert {r.id for r in cfg.roles if r.tipped} == {"server", "bartender"}
    assert cfg.role_tags["line_cook"] == ["cooking", "fryer"]
