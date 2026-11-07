"""Unit tests: OpenRouter client (mock transport, no network), cache, retry, truncation, prompt, mocks."""
from __future__ import annotations

import asyncio
import json

import httpx

from shiftwright_contracts.models import Schedule
from shiftwright_evals import mock, prompts
from shiftwright_evals.llm import CachedClient, OpenRouterClient
from shiftwright_evals.suites import make_case
from shiftwright_evals.systems import BaselineSystem, extract_json
from shiftwright_validator import validate_raw


def _transport(replies: list[dict], seen: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "x/m", "top_provider": {"max_completion_tokens": 12345}}]})
        seen.append(json.loads(request.content))
        r = replies[min(len(seen) - 1, len(replies) - 1)]
        return httpx.Response(200, json={"model": "x/m", "choices": [{"message": {"content": r["text"]},
                                                                       "finish_reason": r.get("finish", "stop")}]})
    return httpx.MockTransport(handler)


def test_openrouter_request_shape_retry_and_cache(tmp_path):
    case = make_case("weekly", "S", "easy", 1)
    good = mock._fence(mock._schedule(case.config.model_dump(mode="json"), []))
    seen: list[dict] = []
    client = OpenRouterClient(api_key="test", transport=_transport([{"text": "no json here"}, {"text": good}], seen))
    cached = CachedClient(client, tmp_path)
    sysm = BaselineSystem("x/m", cached)
    out = asyncio.run(sysm.weekly(case.config))
    assert out.outcome == "ok" and len(out.attempts) == 2
    assert seen[0]["temperature"] == 0 and seen[0]["max_tokens"] == 12345
    assert "parsed" in seen[1]["messages"][-1]["content"]  # the retry message
    assert "raw_output.attempt1.txt" in out.extra_files
    # Second run: served from the cache, no new requests.
    n = len(seen)
    out2 = asyncio.run(BaselineSystem("x/m", cached).weekly(case.config))
    assert len(seen) == n and cached.hits == 2 and out2.raw_text == out.raw_text


def test_truncated_is_an_outcome_and_not_retried(tmp_path):
    case = make_case("weekly", "S", "easy", 1)
    seen: list[dict] = []
    client = OpenRouterClient(api_key="test", transport=_transport([{"text": '{"shifts": [', "finish": "length"}], seen))
    out = asyncio.run(BaselineSystem("x/m", CachedClient(client, None)).weekly(case.config))
    assert out.outcome == "truncated" and len(seen) == 1


def test_http_error_is_an_outcome(tmp_path):
    case = make_case("weekly", "S", "easy", 1)
    t = httpx.MockTransport(lambda r: httpx.Response(429, text="rate limited"))
    out = asyncio.run(BaselineSystem("x/m", CachedClient(OpenRouterClient(api_key="k", transport=t), tmp_path)).weekly(case.config))
    assert out.outcome == "error" and "429" in out.note
    assert not list(tmp_path.glob("*.json"))  # errors are not cached


def test_prompt_is_complete():
    case = make_case("weekly", "S", "legal_trap", 1, "CA")
    text = prompts.render(prompts.weekly_messages(case.config))
    assert prompts.INSTRUCTION in text
    assert case.config.model_dump_json() in text  # the full config, law pack included
    assert '"law_pack":{' in text and "CA." in text
    assert json.dumps(Schedule.model_json_schema(), separators=(",", ":")) in text
    assert "minutes after local midnight" in text


def test_extract_json():
    assert extract_json('prose ```json\n{"a":1}\n``` more')[0] == {"a": 1}
    assert extract_json("nothing")[0] is None
    assert extract_json('{"a": [1,')[0] is None


def _mock_out(kind, case):
    cfg = case.config.model_dump(mode="json")
    orig = mock._pick
    mock._pick = lambda model, store_id, kinds, suite="weekly": kind
    try:
        return mock.weekly("mock-a", cfg, "")
    finally:
        mock._pick = orig


def test_mock_kinds_trigger_the_intended_validator_codes():
    case = make_case("weekly", "S", "legal_trap", 1, "CA")
    codes = lambda text: {v.code.value for v in validate_raw(case.config, text).violations}  # noqa: E731
    assert "unknown_entity" in codes(_mock_out("hallucinated_employee", case)[0])
    assert "minor_prohibited_role" in codes(_mock_out("minor_on_forklift", case)[0])
    assert "budget_hours" in codes(_mock_out("over_budget", case)[0])
    text, finish = _mock_out("truncated", case)
    assert finish == "length" and extract_json(text)[0] is None
    assert extract_json(_mock_out("unparseable", case)[0])[0] is None


def test_mock_false_feasible_on_infeasible_store():
    case = make_case("honesty", "S", "infeasible", 1)
    text, _ = _mock_out("sloppy", case)
    rep = validate_raw(case.config, text)
    assert extract_json(text)[0]["status"] == "feasible"
    assert not rep.passed


def test_budget_guard_stops_on_projection():
    from shiftwright_evals.llm import BudgetGuard, ChatResult

    class Paid:
        calls = 0

        async def complete(self, model, messages):
            Paid.calls += 1
            return ChatResult("{}", "stop", 0.0, model, usage={"cost": 5.0, "completion_tokens": 10})

    guard = BudgetGuard(Paid(), budget_usd=42, planned_calls=10, log=lambda *_: None)

    async def go():
        return [await guard.complete("m", [{"role": "user", "content": "x"}]) for _ in range(10)]

    results = asyncio.run(go())
    # After 3 calls at $5 the projection is $50 > $42: no further paid calls.
    assert Paid.calls == 3 and guard.stopped and guard.spent == 15.0
    assert results[-1].error and "budget guard" in results[-1].error


def test_mock_assignment_is_keyed_on_store_and_covers_every_kind():
    stores = [f"gen-{k.split('-', 1)[0]}-{k.split('-', 1)[1]}-1" for k in mock.QUICK_ORDER]
    for model in mock.MOCK_MODELS:
        kinds = mock.WEEKLY_KINDS[model]
        picked = [mock._pick(model, sid, kinds) for sid in stores]
        assert picked == [mock._pick(model, sid, kinds) for sid in stores]  # deterministic
    assert set(mock._pick("mock-a", sid, mock.WEEKLY_KINDS["mock-a"]) for sid in stores) == set(mock.WEEKLY_KINDS["mock-a"])
    assert mock._pick("mock-a", "gen-s-infeasible-1", mock.WEEKLY_KINDS["mock-a"]) == "sloppy"
