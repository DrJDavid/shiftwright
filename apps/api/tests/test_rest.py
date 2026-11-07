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
    assert [c.id for c in rd.checks][:7] == [
        "store_basics", "jurisdiction", "roles", "employees", "training", "demand", "budget"]

    sid = _put_tiny(client)
    rd = Readiness.model_validate(client.get(f"/api/stores/{sid}/readiness").json())
    assert rd.ready is True, rd


def test_laws_resolve(client):
    r = client.get("/api/laws/resolve", params={"state": "TX", "city": "austin"})
    assert r.status_code == 200
    LawPack.model_validate(r.json())
