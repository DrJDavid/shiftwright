"""Acceptance: scripted onboarding from scratch reaches readiness.ready = true (headless chat).

The fake LLM drives the same tool calls a real agent would; the point is that the tool
layer + headless card mode can build a full config. Live-LLM behaviour is in test_live_agent.py.
"""
from __future__ import annotations

from api_helpers import make_store, parse_sse, tiny_config
from shiftwright_api.agent.llm import call, say


def test_scripted_onboarding_reaches_ready(client, fake_llm):
    tiny = tiny_config()
    steps = [call("ask_store_basics"), call("ask_payroll"), call("ask_roles")]
    steps += [call("upsert_employee", employee=e.model_dump(mode="json")) for e in tiny.employees]
    steps += [call("set_demand", requirements=[d.model_dump(mode="json") for d in tiny.demand])]
    steps += [call("readiness_check"), say("You're ready to build the week.")]
    fake_llm.script(steps)

    sid = make_store(client, template="empty")["store"]["id"]
    store = tiny.store.model_dump(mode="json")
    script = {
        "store_basics": [{k: store[k] for k in ("name", "jurisdiction", "slot_minutes", "hours")}],
        "payroll": [tiny.budget.model_dump(mode="json")],
        "roles": [{"departments": [d.model_dump(mode="json") for d in tiny.departments],
                   "roles": [r.model_dump(mode="json") for r in tiny.roles]}],
    }
    r = client.post(f"/api/stores/{sid}/chat?auto_cards=scripted",
                    json={"mode": "onboard", "messages": [{"role": "user", "content": "new store"}], "card_script": script})
    events = parse_sse(r.text)
    assert "error" not in [e for e, _ in events], events
    readiness_result = [m for m in fake_llm.calls[-1] if m["role"] == "tool"][-1]["content"]
    assert '"ready": true' in readiness_result
    assert client.get(f"/api/stores/{sid}/readiness").json()["ready"] is True


def test_business_basics_from_create_form_are_done_at_first_readiness_check(client, fake_llm):
    import json

    fake_llm.script([call("readiness_check"), say("A taqueria in Chicago. What are your open hours?")])
    cfg = make_store(client, template="empty", name="Harbor Grill", jurisdiction={"state": "IL", "city": "chicago"},
                     sector="food", business_description="  30-seat family taqueria ")
    assert cfg["store"]["sector"] == "food"
    assert cfg["store"]["business_description"] == "30-seat family taqueria"
    sid = cfg["store"]["id"]
    assert client.get(f"/api/stores/{sid}/config").json()["store"]["sector"] == "food"

    r = client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "hi"}]})
    assert "error" not in [e for e, _ in parse_sse(r.text)]
    first_check = json.loads([m for m in fake_llm.calls[-1] if m["role"] == "tool"][0]["content"])
    business = {c["id"]: c for c in first_check["checks"]}["business_type"]
    assert business["ok"] is True and business["severity"] == "ok"
    assert business["detail"] == "food: 30-seat family taqueria"


def test_create_without_business_basics_still_works(client):
    cfg = make_store(client, template="empty")
    assert cfg["store"]["sector"] is None and cfg["store"]["business_description"] == ""
    bad = client.post("/api/stores", json={"template": "empty", "name": "X", "jurisdiction": {"state": "TX"},
                                           "sector": "spaceport"})
    assert bad.status_code == 422


def test_unmodeled_rule_is_logged(client, fake_llm):
    fake_llm.script([call("log_unmodeled", text="Sam is better with customers",
                          reason="No ConstraintKind expresses customer skill."), say("Logged.")])
    sid = make_store(client)["store"]["id"]
    events = parse_sse(client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [
        {"role": "user", "content": "Sam is better with customers"}]}).text)
    assert "config" in [e for e, _ in events]
    cfg = client.get(f"/api/stores/{sid}/config").json()
    assert cfg["unmodeled"][0]["text"] == "Sam is better with customers"


def test_lookup_law_tool(client, fake_llm):
    fake_llm.script([call("lookup_law", state="TX", rule_type="weekly_overtime"), say("Per the dataset...")])
    sid = make_store(client)["store"]["id"]
    client.post(f"/api/stores/{sid}/chat", json={"mode": "review", "messages": [{"role": "user", "content": "OT law?"}]})
    tool_msg = [m for m in fake_llm.calls[-1] if m["role"] == "tool"][0]
    assert "coverage" in tool_msg["content"]
