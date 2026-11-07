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
