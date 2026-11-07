"""Token streaming: OpenRouter SSE parsing and text deltas forwarded as they arrive."""
from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from api_helpers import make_store, parse_sse
from shiftwright_api.agent import llm as llm_mod
from shiftwright_api.agent.llm import LLMResponse, OpenRouterClient, ToolCall
from shiftwright_api.main import create_app
from shiftwright_contracts.models import Event


def _sse_body(chunks: list[dict]) -> bytes:
    lines = [": OPENROUTER PROCESSING", ""]
    for c in chunks:
        lines += [f"data: {json.dumps(c)}", ""]
    lines += ["data: [DONE]", ""]
    return "\n".join(lines).encode()


def test_openrouter_stream_parses_text_and_tool_calls(monkeypatch):
    chunks = [
        {"choices": [{"delta": {"content": "Let me "}}]},
        {"choices": [{"delta": {"content": "check."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "lookup_law",
                                                                                         "arguments": '{"to'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'pic": "overtime"}'}}]}}]},
    ]
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=_sse_body(chunks),
                                                               headers={"content-type": "text/event-stream"}))
    real = httpx.AsyncClient
    monkeypatch.setattr(llm_mod.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))

    async def run():
        return [p async for p in OpenRouterClient("k", "m").stream([{"role": "user", "content": "x"}], [])]

    out = asyncio.run(run())
    assert out[:2] == ["Let me ", "check."]
    final = out[-1]
    assert isinstance(final, LLMResponse) and final.content == "Let me check."
    assert final.tool_calls == [ToolCall(id="call_a", name="lookup_law", arguments={"topic": "overtime"})]


class StreamingFake:
    def __init__(self, pieces):
        self.pieces = pieces

    async def complete(self, messages, tools):  # pragma: no cover - stream is preferred
        raise AssertionError("stream() should be used")

    async def stream(self, messages, tools):
        for p in self.pieces:
            yield p
        yield LLMResponse(content="".join(self.pieces))


def test_chat_forwards_each_token(settings):
    with TestClient(create_app(settings=settings, llm=StreamingFake(["Hi", " there", "!"]))) as c:
        sid = make_store(c)["store"]["id"]
        r = c.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "x"}]})
        events = parse_sse(r.text)
        assert events == [("text", {"delta": "Hi"}), ("text", {"delta": " there"}), ("text", {"delta": "!"}),
                          ("done", {})]


def test_text_from_separate_steps_is_separated(settings):
    from shiftwright_api.agent.llm import FakeLLM, call, say
    fake = FakeLLM([LLMResponse(content="Saved.", tool_calls=call("readiness_check").tool_calls), say("Next up.")])
    with TestClient(create_app(settings=settings, llm=fake)) as c:
        sid = make_store(c)["store"]["id"]
        events = parse_sse(c.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [
            {"role": "user", "content": "x"}]}).text)
        assert [d["delta"] for e, d in events if e == "text"] == ["Saved.", "\n\nNext up."]


def test_coverage_grid_widens_to_cover_events(settings):
    from shiftwright_api.agent.llm import FakeLLM, call, say
    from api_helpers import tiny_config
    fake = FakeLLM([call("ask_coverage_grid", day_type="truck_day"), say("ok")])
    with TestClient(create_app(settings=settings, llm=fake)) as c:
        sid = make_store(c)["store"]["id"]
        cfg = tiny_config().model_copy(deep=True)
        cfg.store.id = sid
        day = next(h.day for h in cfg.store.hours if h.close > h.open and h.day < 5)
        cfg.events = [e for e in cfg.events if e.kind.value != "truck"]
        cfg.events.append(Event(id="ev_t", kind="truck", day=day, start=240, end=600))
        assert c.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json")).status_code == 200
        events = parse_sse(c.post(f"/api/stores/{sid}/chat?auto_cards=scripted", json={
            "mode": "onboard", "messages": [{"role": "user", "content": "x"}], "card_script": {}}).text)
        card = next(d for e, d in events if e == "card")
        assert card["props"]["days"] == [day] and card["props"]["start_minute"] == 240


def test_chat_stream_pings_while_a_card_waits(client, fake_llm, monkeypatch):
    """A card the leader hasn't answered keeps the connection alive with SSE comments, then carries on."""
    import threading
    import time

    from api_helpers import make_store
    from shiftwright_api import main as M
    from shiftwright_api.agent.llm import call, say
    monkeypatch.setattr(M, "CHAT_PING_S", 0.05)
    sid = make_store(client, template="tiny")["store"]["id"]
    fake_llm.script([call("ask_payroll"), say("Budget saved.")])
    body = {}

    def answer_later():
        time.sleep(0.4)
        while True:
            r = client.post(f"/api/stores/{sid}/chat/card", json={"card_id": body.get("card", ""), "result": {
                "weekly_hours_cap": 200, "weekly_dollar_cap": None, "overtime_allowed": False, "approvals": []}})
            if r.status_code == 200:
                return
            time.sleep(0.05)

    with client.stream("POST", f"/api/stores/{sid}/chat", json={"mode": "onboard",
                                                               "messages": [{"role": "user", "content": "budget"}]}) as r:
        text = ""
        t = None
        for chunk in r.iter_text():
            text += chunk
            if "event: card" in text and t is None:
                import json as _j
                block = text.split("event: card", 1)[1].split("\n\n", 1)[0]
                body["card"] = _j.loads(block.split("data: ", 1)[1])["card_id"]
                t = threading.Thread(target=answer_later)
                t.start()
        t.join()
    after_card = text.split("event: card", 1)[1]
    assert ": ping" in after_card and "Budget saved." in text
