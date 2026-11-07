"""Acceptance tests that need the real agent model (skipped without OPENROUTER_API_KEY)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from api_helpers import make_store
from shiftwright_api.agent.llm import OpenRouterClient
from shiftwright_api.main import create_app
from shiftwright_api.settings import Settings

pytestmark = pytest.mark.skipif(not os.environ.get("OPENROUTER_API_KEY"), reason="needs OPENROUTER_API_KEY")


class Recorder(OpenRouterClient):
    def __init__(self, s):
        super().__init__(s.openrouter_api_key, s.agent_model)
        self.tool_names: list[str] = []

    async def complete(self, messages, tools):
        resp = await super().complete(messages, tools)
        self.tool_names += [tc.name for tc in resp.tool_calls]
        return resp


@pytest.fixture
def live(tmp_path):
    s = Settings.from_env()
    s.database_url = f"sqlite:///{tmp_path}/live.db"
    rec = Recorder(s)
    with TestClient(create_app(settings=s, llm=rec)) as c:
        yield c, rec


def _say(c, sid, text, mode="onboard"):
    return c.post(f"/api/stores/{sid}/chat?auto_cards=scripted",
                  json={"mode": mode, "messages": [{"role": "user", "content": text}], "card_script": {}})


def test_sam_better_with_customers(live):
    c, rec = live
    sid = make_store(c, template="bigbox_small")["store"]["id"]
    r = _say(c, sid, "Sam is better with customers.")
    assert r.status_code == 200 and "event: error" not in r.text, r.text[-500:]
    assert "log_unmodeled" in rec.tool_names or "propose_rule" in rec.tool_names


def test_overtime_question_uses_lookup_law(live):
    c, rec = live
    sid = make_store(c, template="bigbox_small")["store"]["id"]
    r = _say(c, sid, "What's the overtime law here?", mode="review")
    assert r.status_code == 200 and "event: error" not in r.text, r.text[-500:]
    assert "lookup_law" in rec.tool_names
