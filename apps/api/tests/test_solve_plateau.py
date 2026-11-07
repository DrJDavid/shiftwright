"""C4: `/solve {}` and the agent's dry_run_solve ask the engine to stop when it stops improving
(time_limit_s=None, capped at SOLVE_MAX_S); an explicit time_limit_s still wins."""
from __future__ import annotations

from api_helpers import make_store

from shiftwright_api import integrations


def _capture(monkeypatch) -> list:
    calls = []

    def fake_engine(config, time_limit_s=20, previous=None, **kw):
        calls.append((time_limit_s, kw))
        return integrations._stub_solve(config)
    monkeypatch.setattr(integrations, "_lookup", lambda spec: fake_engine if spec is integrations._SOLVE else None)
    return calls


def test_solve_without_limit_uses_plateau_mode(client, monkeypatch):
    sid = make_store(client, template="tiny")["store"]["id"]
    calls = _capture(monkeypatch)
    assert client.post(f"/api/stores/{sid}/solve", json={}).status_code in (200, 503)
    assert calls == [(None, {"max_s": integrations.SOLVE_MAX_S})]


def test_explicit_time_limit_wins(client, monkeypatch):
    sid = make_store(client, template="tiny")["store"]["id"]
    calls = _capture(monkeypatch)
    client.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 7})
    assert calls == [(7, {})]
