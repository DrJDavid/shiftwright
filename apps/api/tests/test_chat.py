"""Chat SSE loop: text, cards (store_basics, payroll), config events, headless mode."""
from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn

from api_helpers import make_store, parse_sse
from shiftwright_api.agent.llm import FakeLLM, call, say
from shiftwright_api.main import create_app
from shiftwright_contracts.models import StoreConfig


def test_text_only_turn(client, fake_llm):
    fake_llm.script([say("Hi! Let's set up your store.")])
    sid = make_store(client)["store"]["id"]
    r = client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert events[0] == ("text", {"delta": "Hi! Let's set up your store."})
    assert events[-1] == ("done", {})


def test_headless_cards_apply_and_emit_config(client, fake_llm):
    fake_llm.script([
        call("ask_store_basics"),
        call("ask_payroll"),
        say("All set."),
    ])
    cfg0 = make_store(client, template="empty")
    sid = cfg0["store"]["id"]
    script = {
        "store_basics": [{"name": "Store #0417", "hours": [{"day": d, "open": 480, "close": 1320} for d in range(7)]}],
        "payroll": [{"weekly_hours_cap": 1200, "overtime_allowed": False}],
    }
    r = client.post(f"/api/stores/{sid}/chat?auto_cards=scripted",
                    json={"mode": "onboard", "messages": [{"role": "user", "content": "set me up"}], "card_script": script})
    events = parse_sse(r.text)
    kinds = [e for e, _ in events]
    cards = [d for e, d in events if e == "card"]
    assert [c["card_type"] for c in cards] == ["store_basics", "payroll"]
    assert cards[0]["props"]["name"] == "Store #0417"          # prefilled from Store
    assert "weekly_hours_cap" in cards[1]["props"]              # prefilled from Budget
    assert kinds.count("config") == 2
    assert kinds[-1] == "done" and "error" not in kinds

    cfg = StoreConfig.model_validate(client.get(f"/api/stores/{sid}/config").json())
    assert len(cfg.store.hours) == 7
    assert cfg.budget.weekly_hours_cap == 1200
    assert cfg.config_version == cfg0["config_version"] + 2

    # The LLM saw each card result as the tool result.
    tool_msgs = [m for m in fake_llm.calls[-1] if m["role"] == "tool"]
    assert len(tool_msgs) == 2


def test_transcript_kept_server_side(client, fake_llm):
    fake_llm.script([say("one"), say("two")])
    sid = make_store(client)["store"]["id"]
    for text in ("a", "b"):
        client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": text}]})
    second = fake_llm.calls[-1]
    assert [m["content"] for m in second if m["role"] == "user"] == ["a", "b"]
    assert second[0]["role"] == "system"


def test_mutation_error_returned_to_llm(client, fake_llm):
    fake_llm.script([call("set_budget", weekly_hours_cap="lots"), say("Sorry.")])
    sid = make_store(client)["store"]["id"]
    events = parse_sse(client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "x"}]}).text)
    assert "config" not in [e for e, _ in events]
    tool_msg = [m for m in fake_llm.calls[-1] if m["role"] == "tool"][0]
    assert "error" in tool_msg["content"]


def test_no_api_key_gives_error_event(settings):
    from fastapi.testclient import TestClient
    app = create_app(settings=settings)  # no fake llm, no key
    with TestClient(app) as c:
        sid = make_store(c)["store"]["id"]
        events = parse_sse(c.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "x"}]}).text)
    assert events[0][0] == "error"
    assert "OPENROUTER_API_KEY" in events[0][1]["message"]


# --- real server: the turn pauses on a card and resumes on /chat/card -------- #
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(settings):
    llm = FakeLLM([call("ask_payroll"), say("Budget saved.")])
    app = create_app(settings=settings, llm=llm)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", llm
    server.should_exit = True
    t.join(5)


def test_card_pauses_and_resumes(live_server):
    base, llm = live_server
    with httpx.Client(base_url=base, timeout=10) as c:
        sid = make_store(c)["store"]["id"]
        events = []
        with c.stream("POST", f"/api/stores/{sid}/chat",
                      json={"mode": "onboard", "messages": [{"role": "user", "content": "budget"}]}) as resp:
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    block, buf = buf.split("\n\n", 1)
                    ev = parse_sse(block + "\n\n")[0]
                    events.append(ev)
                    if ev[0] == "card":
                        card = ev[1]
                        assert len(llm.calls) == 1  # paused: LLM not called again yet
                        r = c.post(f"/api/stores/{sid}/chat/card",
                                   json={"card_id": card["card_id"], "result": {"weekly_hours_cap": 900}})
                        assert r.status_code == 200, r.text
        assert [e for e, _ in events][-1] == "done"
        assert ("text", {"delta": "Budget saved."}) in events
        assert c.get(f"/api/stores/{sid}/config").json()["budget"]["weekly_hours_cap"] == 900
        assert c.post(f"/api/stores/{sid}/chat/card", json={"card_id": "nope", "result": {}}).status_code == 404
