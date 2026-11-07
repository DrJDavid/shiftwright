"""Accounts, sessions and workplace ownership (PUNCHLIST A1)."""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from api_helpers import make_store, signup
from shiftwright_api.db import Database
from shiftwright_api.main import create_app
from shiftwright_api.settings import Settings
from shiftwright_contracts.models import StoreConfig


@pytest.fixture
def anon(app):
    """A second browser on the same server, not signed in."""
    with TestClient(app) as c:
        yield c


def _cookie_header(r) -> str:
    return "; ".join(v for k, v in r.headers.multi_items() if k == "set-cookie")


# ------------------------------------------------------------------ signup / login / logout / me
def test_signup_me_logout(anon):
    r = anon.post("/api/auth/signup", json={"email": "ana@example.com", "password": "correct horse", "name": "Ana"})
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert set(user) == {"id", "email", "name"}
    assert user["email"] == "ana@example.com" and user["name"] == "Ana"
    cookie = _cookie_header(r)
    assert "sw_session=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert "Max-Age=2592000" in cookie and "Secure" not in cookie  # 30 days; plain http in tests

    assert anon.get("/api/auth/me").json() == {"user": user}
    r = anon.post("/api/auth/logout")
    assert r.status_code == 204
    assert 'sw_session=""' in _cookie_header(r) or "Max-Age=0" in _cookie_header(r)
    assert anon.get("/api/auth/me").status_code == 401


def test_logout_kills_the_session_server_side(app, anon):
    signup(anon, email="ana@example.com")
    token = anon.cookies.get("sw_session")
    anon.post("/api/auth/logout")
    with TestClient(app, cookies={"sw_session": token}) as replay:
        assert replay.get("/api/auth/me").status_code == 401


def test_login(app, anon):
    signup(anon, email="Ana@Example.com", password="correct horse")
    anon.post("/api/auth/logout")
    r = anon.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["email"] == "Ana@Example.com"
    assert "sw_session=" in _cookie_header(r)
    assert anon.get("/api/auth/me").status_code == 200


def test_duplicate_email_409(anon):
    signup(anon, email="ana@example.com")
    r = anon.post("/api/auth/signup", json={"email": "ANA@example.com", "password": "another one", "name": "A2"})
    assert r.status_code == 409


def test_wrong_password_and_unknown_email_401_same_message(anon):
    signup(anon, email="ana@example.com", password="correct horse")
    anon.post("/api/auth/logout")
    bad = anon.post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong horse"})
    unknown = anon.post("/api/auth/login", json={"email": "bob@example.com", "password": "correct horse"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    assert anon.get("/api/auth/me").status_code == 401


def test_signup_validation(anon):
    assert anon.post("/api/auth/signup", json={"email": "a@b.co", "password": "short", "name": "A"}).status_code == 422
    assert anon.post("/api/auth/signup", json={"email": "nope", "password": "long enough", "name": "A"}).status_code == 422
    assert anon.post("/api/auth/signup", json={"email": "a@b.co", "password": "long enough", "name": " "}).status_code == 422


def test_password_is_hashed_with_scrypt(app, anon):
    signup(anon, email="ana@example.com", password="correct horse")
    row = app.state.db._q("SELECT pw_hash FROM users")[0][0]
    assert row.startswith("scrypt$") and "correct horse" not in row


def test_secure_cookie_on_https(anon):
    r = anon.post("/api/auth/signup", json={"email": "a@b.co", "password": "long enough", "name": "A"},
                  headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in _cookie_header(r)


def test_rate_limit_10_attempts_per_ip(anon):
    for i in range(10):
        r = anon.post("/api/auth/login", json={"email": f"x{i}@example.com", "password": "whatever1"})
        assert r.status_code == 401
    r = anon.post("/api/auth/login", json={"email": "x@example.com", "password": "whatever1"})
    assert r.status_code == 429
    assert anon.post("/api/auth/signup", json={"email": "new@b.co", "password": "long enough",
                                               "name": "N"}).status_code == 429


# ------------------------------------------------------------------ public vs private routes
def test_public_routes_stay_public(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/templates").status_code == 200
    r = anon.post("/api/sms/inbound", data={"From": "+15550000000", "Body": "YES"})
    assert r.status_code == 200
    assert anon.get("/api/auth/me").status_code == 401  # reachable, just not signed in


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/stores"),
    ("GET", "/api/workplaces"),
    ("POST", "/api/workplaces/sample"),
    ("GET", "/api/laws/resolve?state=TX"),
    ("GET", "/api/stores/whatever/config"),
    ("POST", "/api/sms/mock-reply"),
])
def test_private_routes_need_a_session(anon, method, path):
    assert anon.request(method, path, json={}).status_code == 401


def test_health_reports_auth(client):
    h = client.get("/api/health").json()
    assert h["auth_required"] is True and h["demo_key_required"] is False


# ------------------------------------------------------------------ ownership
def test_other_users_store_is_404_everywhere(client, app):
    sid = make_store(client, template="tiny")["store"]["id"]
    assert client.get(f"/api/stores/{sid}/config").status_code == 200
    with TestClient(app) as b:
        signup(b, email="bob@example.com")
        cfg = client.get(f"/api/stores/{sid}/config").json()
        checks = [
            ("GET", f"/api/stores/{sid}/config", None),
            ("PUT", f"/api/stores/{sid}/config", cfg),
            ("GET", f"/api/stores/{sid}/readiness", None),
            ("POST", f"/api/stores/{sid}/solve", {"time_limit_s": 5}),
            ("GET", f"/api/stores/{sid}/schedule", None),
            ("POST", f"/api/stores/{sid}/chat", {"mode": "onboard", "messages": [{"role": "user", "content": "x"}]}),
            ("POST", f"/api/stores/{sid}/chat/card", {"card_id": "c", "result": {}}),
            ("POST", f"/api/stores/{sid}/fix", {"callouts": [], "day": 5, "now": 364}),
            ("POST", f"/api/stores/{sid}/fix/apply", {"plan_id": "p"}),
            ("POST", f"/api/stores/{sid}/outreach/start", {"plan_id": "p"}),
            ("GET", f"/api/stores/{sid}/outreach", None),
            ("GET", f"/api/stores/{sid}/outreach/stream", None),
            ("GET", f"/api/stores/{sid}/audit", None),
        ]
        for method, path, body in checks:
            r = b.request(method, path, json=body)
            assert r.status_code == 404, (method, path, r.status_code, r.text)
        # same answer as a store that doesn't exist, so ids can't be probed
        assert b.get("/api/stores/st_doesnotexist/config").json()["detail"].startswith("Store ")
        assert b.get("/api/workplaces").json() == {"workplaces": []}
    # the owner is unaffected
    assert client.get(f"/api/stores/{sid}/config").json()["store"]["name"] == cfg["store"]["name"]


def test_workplaces_lists_mine_only(client, app):
    a1 = make_store(client, template="empty", name="Harbor Grill",
                    jurisdiction={"state": "IL", "city": "chicago"})["store"]["id"]
    with TestClient(app) as b:
        signup(b, email="bob@example.com")
        make_store(b, template="empty", name="Bob's")
    wp = client.get("/api/workplaces").json()["workplaces"]
    assert [w["id"] for w in wp] == [a1]
    w = wp[0]
    assert {"id", "name", "sector", "city", "state", "updated_at", "has_schedule"} <= set(w)
    assert (w["name"], w["city"], w["state"], w["has_schedule"]) == ("Harbor Grill", "chicago", "IL", False)


def test_workplace_has_schedule_after_solve(client):
    sid = make_store(client, template="tiny")["store"]["id"]
    assert client.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 5}).status_code == 200
    (w,) = client.get("/api/workplaces").json()["workplaces"]
    assert w["has_schedule"] is True


def test_sample_workplace_is_owned_and_independent(client, app):
    tpl = {t["id"]: t for t in client.get("/api/templates").json()["templates"]}
    assert "tiny" in tpl
    r = client.post("/api/workplaces/sample", json={"template": "tiny"})
    assert r.status_code == 200, r.text
    s1 = StoreConfig.model_validate(r.json())
    assert s1.store.name.startswith("Sample: ")

    edited = s1.model_copy(deep=True)
    edited.employees = edited.employees[:1]
    assert client.put(f"/api/stores/{s1.store.id}/config", json=edited.model_dump(mode="json")).status_code == 200

    s2 = StoreConfig.model_validate(client.post("/api/workplaces/sample", json={"template": "tiny"}).json())
    assert s2.store.id != s1.store.id
    assert len(s2.employees) == len(s1.employees) > 1  # editing one sample didn't touch the template

    ids = {w["id"] for w in client.get("/api/workplaces").json()["workplaces"]}
    assert ids == {s1.store.id, s2.store.id}
    with TestClient(app) as b:
        signup(b, email="bob@example.com")
        assert b.get(f"/api/stores/{s1.store.id}/config").status_code == 404


def test_sample_needs_a_demo_template(client):
    assert client.post("/api/workplaces/sample", json={"template": "bigbox_small"}).status_code == 422
    assert client.post("/api/workplaces/sample", json={"template": "demo_atlantis"}).status_code == 422


# ------------------------------------------------------------------ settings + migration
def test_auth_off_keeps_the_old_open_api(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path}/open.db", messenger="mock", agent_model="fake/model",
                 auth_required=False)
    with TestClient(create_app(settings=s)) as c:
        r = c.post("/api/stores", json={"template": "empty", "name": "X", "jurisdiction": {"state": "TX"}})
        assert r.status_code == 200
        assert c.get(f"/api/stores/{r.json()['store']['id']}/config").status_code == 200
        assert c.get("/api/health").json()["auth_required"] is False


def test_demo_key_middleware_off_when_auth_on(tmp_path):
    s = Settings(database_url=f"sqlite:///{tmp_path}/k.db", messenger="mock", agent_model="fake/model",
                 auth_required=True, demo_key="sekrit")
    with TestClient(create_app(settings=s)) as c:
        signup(c)
        assert make_store(c)  # no X-Demo-Key header needed
        assert c.get("/api/health").json()["demo_key_required"] is False


def test_from_env_defaults_auth_on(monkeypatch):
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)
    assert Settings.from_env().auth_required is True
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    assert Settings.from_env().auth_required is False


def test_migrates_stores_without_owner_column(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE stores (id TEXT PRIMARY KEY, config_json TEXT NOT NULL, config_version INTEGER NOT NULL,"
                " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    con.commit()
    con.close()
    db = Database(str(path))
    cols = {r[1] for r in db._q("PRAGMA table_info(stores)")}
    assert "owner_id" in cols
