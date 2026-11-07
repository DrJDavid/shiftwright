"""Realistic suite: same raw inputs for chat baselines and Shiftwright's real intake (fake agent, no key)."""
from __future__ import annotations

import asyncio
import json

from shiftwright_evals import realistic as R
from shiftwright_evals.suites import make_case
from shiftwright_validator import validate_raw


def _case():
    return make_case("realistic", "S", "legal_trap", 1, "CA")


def test_prompt_has_only_raw_inputs():
    case = _case()
    msgs = R.chat_messages(case, R.export_texts(case))
    assert len(msgs) == 1 and msgs[0]["role"] == "user"  # no system prompt
    text = msgs[0]["content"]
    assert text.startswith("I manage a big-box store in California.")
    assert case.scenario.narrative in text and "TM_ID,Date,Start,End,Job" in text
    assert "roster.csv:" in text and "forecast.csv:" in text
    for leak in ("law_pack", "CA.meal_break", "always_staffed", '"employees"', "minutes after local midnight"):
        assert leak not in text


def test_csv_reply_maps_to_true_ids_and_breaks():
    case = _case()
    cfg = case.config
    e = cfg.employees[5]
    tm = R.tm_id(e.id)
    reply = ("Assumptions:\n- One.\n- Two.\n\n```csv\nTM_ID,Date,Start,End,Job\n"
             f"{tm},11/09/2026,8:00 AM,12:00 PM,CASH\n{tm},11/09/2026,12:30 PM,4:30 PM,CASH\n"
             f"999999,11/10/2026,9:00 AM,5:00 PM,CASH\n```\n")
    sched, info = R.csv_to_schedule(reply, cfg, "chat:test")
    assert info["rows"] == 3 and info["assumptions"] == 2
    s0 = next(s for s in sched["shifts"] if s["employee_id"] == e.id)
    assert (s0["day"], s0["start"], s0["end"]) == (0, 480, 990)
    assert s0["breaks"] == [{"start": 720, "end": 750, "kind": "meal", "paid": False}]
    assert [g["role_id"] for g in s0["segments"]] == ["cashier", "cashier"]
    rep = validate_raw(cfg, sched)
    assert "unknown_entity" in {v.code.value for v in rep.violations}  # 999999 isn't on the roster
    assert R.csv_to_schedule("no table here", cfg, "x")[0] is None


def test_accept_prefill_never_invents_answers():
    assert R.accept_prefill("payroll", {"weekly_hours_cap": 0, "approvals": []}) == {"weekly_hours_cap": 0}
    assert R.accept_prefill("department_staffing", {"suggested": {"cashier": {"base": 1}}}) == \
        {"staffing": {"cashier": {"base": 1}}}
    assert R.accept_prefill("propose_rule", {"constraint": {"strength": "hard"}}) == {"decision": "hard"}
    assert R.accept_prefill("tradeoff", {"options": [{"id": "a"}, {"id": "b"}]}) == {"option_id": "a"}
    assert R.accept_prefill("something_new", {}) == {"cancelled": True}


def test_shiftwright_intake_runs_with_fake_agent_and_no_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    case = _case()
    out = asyncio.run(R.ShiftwrightIntake(agent="fake", time_limit_s=5).run_realistic(case))
    assert out.outcome in ("ok", "error"), out.note
    log = json.loads(out.extra_files["intake_log.json"])
    assert {i["kind"] for i in log["imports"]} >= {"roster", "training", "availability", "forecast"}
    assert [c["card_type"] for c in log["cards"]] == ["store_basics", "payroll"]  # prefill accepted
    recall = json.loads(out.extra_files["intake_recall.json"])
    assert recall["checked"] > 0
    if out.outcome == "ok":  # mapped back to the scenario's true ids
        ids = {e.id for e in case.config.employees}
        assert all(s["employee_id"] in ids for s in out.schedule_input["shifts"])


def test_mock_chat_kinds_all_covered_on_quick_retail_stores():
    from shiftwright_evals import mock
    picked = {mock._pick(m, loc, mock.CHAT_KINDS, suite="chat") for m in mock.MOCK_MODELS
              for loc in mock.CHAT_ORDER[:3]}
    assert picked == set(mock.CHAT_KINDS)
