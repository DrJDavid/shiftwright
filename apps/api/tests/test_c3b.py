"""C3b (API side of coverage-first): priority tiers, strength words, build tradeoffs as manager decisions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api_helpers import make_store, parse_sse
from shiftwright_api import integrations, priorities as P, rules, tradeoffs
from shiftwright_api.agent import tools as T
from shiftwright_api.agent.llm import call, say
from shiftwright_api.imports import AUTO_PRIORITY, price_imported_roles
from shiftwright_api.readiness import compute
from shiftwright_contracts.models import ScheduleMetrics, StoreConfig, ValidationReport

TINY = Path(__file__).parents[3] / "packages/scenarios/fixtures/tiny_store.json"


# ------------------------------------------------------------------ priority tiers
def test_levels_are_fixed_tiers_whatever_the_pay():
    assert {k: P.penalty(k) for k in P.LEVELS} == {"must_cover": 300, "important": 200, "nice_to_have": 100}
    d = {"roles": [{"id": "barista", "gap_penalty_per_hour": 0.0}, {"id": "lead", "gap_penalty_per_hour": 7.0}],
         "employees": [{"wage_per_hour": 450, "trained_role_ids": ["barista"]}]}
    P.apply(d, {"barista": "nice_to_have"})
    assert d["roles"][0]["gap_penalty_per_hour"] == 100     # not tied to the $450 wage
    assert d["roles"][1]["gap_penalty_per_hour"] == 7.0     # no level: custom value untouched


def test_imported_roles_default_to_the_important_tier():
    d = {"roles": [{"id": "lod", "gap_penalty_per_hour": 0.0, "description": f"Added from CSV import ({AUTO_PRIORITY}); review."}],
         "employees": [{"wage_per_hour": 31, "trained_role_ids": ["lod"]}]}
    price_imported_roles(d)
    assert d["roles"][0]["gap_penalty_per_hour"] == P.penalty("important") == 200


def test_readiness_no_longer_blocks_on_a_priority_below_pay():
    cfg = StoreConfig(**json.loads(TINY.read_text()))
    role = next(r for r in cfg.roles if any(d.role_id == r.id and d.headcount > 0 for d in cfg.demand))
    role.gap_penalty_per_hour = 1.0  # below every wage: still a valid (low) tier
    check = next(c for c in compute(cfg).checks if c.id == "priorities")
    assert check.ok is True
    role.gap_penalty_per_hour = 0.0  # no priority still blocks
    check = next(c for c in compute(cfg).checks if c.id == "priorities")
    assert check.ok is False and "Pick a priority" in check.detail


# ------------------------------------------------------------------ strength words
def _ctx(client):
    sid = make_store(client, template="tiny")["store"]["id"]
    db = client.app.state.db
    return T.ToolContext(db=db, store_id=sid), db.get_config(sid)


def _rule(cfg) -> dict:
    a, b = cfg.employees[0], cfg.employees[1]
    return {"kind": "not_together", "params": {"employee_ids": [a.id, b.id]}}


def _saved(ctx, cid):
    return next(c for c in ctx.config().constraints if c.id == cid)


@pytest.mark.parametrize("decision,strength,weight", [
    ("firm", "hard", 0), ("strong_preference", "soft", 50), ("preference", "soft", 25),
    ("hard", "hard", 0), ("soft", "soft", 25),  # older clients
])
def test_rule_card_strength_words_map_to_tiers(client, decision, strength, weight):
    ctx, cfg = _ctx(client)
    card = T.propose_rule(ctx, {"constraint": {**_rule(cfg), "id": "c1"}, "level": "strong_preference",
                                "plain_text": "Keep them apart"})
    assert card.props["level"] == "strong_preference" and card.props["constraint"]["weight_dollars"] == 50
    assert [x["label"] for x in card.props["levels"]] == ["Firm rule", "Strong preference", "Preference", "Not a rule"]
    assert card.apply({"decision": decision}).content.get("ok")
    c = _saved(ctx, "c1")
    assert (c.strength.value, c.weight_dollars, c.status.value) == (strength, weight, "confirmed")


def test_rule_card_never_keeps_dollar_weights(client):
    ctx, cfg = _ctx(client)
    card = T.propose_rule(ctx, {"constraint": {**_rule(cfg), "id": "c2", "strength": "soft", "weight_dollars": 400},
                                "plain_text": "x"})
    assert card.props["level"] == "strong_preference" and card.props["constraint"]["weight_dollars"] == 50
    card.apply({"decision": "soft", "weight_dollars": 7})  # an old client's dollar answer snaps to a tier
    assert _saved(ctx, "c2").weight_dollars == 25
    assert card.apply({"decision": "not_a_rule"}).content.get("ok")
    assert _saved(ctx, "c2").status.value == "rejected"


def test_add_constraint_snaps_weights_to_tiers(client):
    ctx, cfg = _ctx(client)
    T.add_constraint(ctx, {"constraint": {**_rule(cfg), "id": "c3", "strength": "soft", "weight_dollars": 1000,
                                          "source": "leader"}})
    T.add_constraint(ctx, {"constraint": {**_rule(cfg), "id": "c4", "strength": "soft", "source": "leader"}})
    assert (_saved(ctx, "c3").weight_dollars, _saved(ctx, "c4").weight_dollars) == (50, 25)
    assert rules.level_of("hard") == "firm"


# ------------------------------------------------------------------ build tradeoffs
def _engine_tradeoffs(role_id: str, rule_id: str) -> list[dict]:
    """In the engine's shape (SEMANTICS #25), deliberately not sorted."""
    return [
        {"id": f"budget_gap:{role_id}:1:840", "kind": "budget_gap", "role_id": role_id, "day": 1,
         "window": [840, 960], "extra_hours": 3.0,
         "if_kept": {"wage_cost": 1000.0, "hours": 60.0, "coverage_pct": 90.0},
         "if_dropped": {"wage_cost": 1051.0, "hours": 63.0, "coverage_pct": 92.5}},
        {"id": f"preference_cost:{rule_id}", "kind": "preference_cost", "rule_id": rule_id, "day": None,
         "if_kept": {"wage_cost": 1000.0, "hours": 60.0, "coverage_pct": 90.0},
         "if_dropped": {"wage_cost": 880.0, "hours": 60.0, "coverage_pct": 90.5}},
        {"id": f"budget_gap:{role_id}:5:600", "kind": "budget_gap", "role_id": role_id, "day": 5,
         "window": [600, 690], "extra_hours": 1.5,
         "if_kept": {"wage_cost": 1000.0, "hours": 60.0, "coverage_pct": 90.0},
         "if_dropped": {"wage_cost": 1024.5, "hours": 61.5, "coverage_pct": 91.0}},
    ]


@pytest.fixture
def built(client, monkeypatch):
    """A tiny store with one soft rule, and an engine that returns known tradeoffs."""
    sid = make_store(client, template="tiny")["store"]["id"]
    cfg = client.get(f"/api/stores/{sid}/config").json()
    a, b = cfg["employees"][0], cfg["employees"][1]
    cfg["constraints"].append({"id": "c_apart", "kind": "not_together", "params": {"employee_ids": [a["id"], b["id"]]},
                               "strength": "soft", "weight_dollars": 25, "status": "confirmed", "source": "leader",
                               "note": f"{a['name']} and {b['name']} work different shifts"})
    assert client.put(f"/api/stores/{sid}/config", json=cfg).status_code == 200
    role = cfg["roles"][0]
    items = _engine_tradeoffs(role["id"], "c_apart")

    def fake_solve(config, time_limit_s=20, previous=None):
        s = integrations._stub_solve(config)
        return s.model_copy(update={"solver_stats": {**(s.solver_stats or {}), "tradeoffs": items}})

    def fake_validate(config, sched):
        return ValidationReport(passed=True, hard_count=0, violations=[],
                                recomputed_metrics=sched.metrics or ScheduleMetrics())
    monkeypatch.setattr(integrations, "solve_week", fake_solve)
    monkeypatch.setattr(integrations, "validate", fake_validate)
    return sid, role, items, a, b


def test_rest_solve_passes_tradeoffs_through_unchanged(client, built):
    sid, _, items, _, _ = built
    r = client.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 5})
    assert r.status_code == 200, r.text
    assert r.json()["schedule"]["solver_stats"]["tradeoffs"] == items
    # saved for the agent, biggest wage difference first
    assert [t["id"] for t in tradeoffs.latest(client.app.state.db, sid)] == [items[1]["id"], items[0]["id"], items[2]["id"]]


def test_build_tradeoffs_become_cards_biggest_first_and_answers_apply(client, fake_llm, built):
    sid, role, items, a, b = built
    order = [items[1]["id"], items[0]["id"], items[2]["id"]]  # $120, $51, $24.50
    fake_llm.script([call("dry_run_solve", time_limit_s=5)] + [call("ask_build_tradeoff", tradeoff_id=t) for t in order]
                    + [say("Done. Want me to rebuild with those changes?")])
    script = {"tradeoff": [{"option_id": f"{order[0]}:drop"}, {"option_id": f"{order[1]}:approve"},
                           {"option_id": f"{order[2]}:leave_open"}]}
    r = client.post(f"/api/stores/{sid}/chat?auto_cards=scripted",
                    json={"mode": "review", "messages": [{"role": "user", "content": "build it"}], "card_script": script})
    events = parse_sse(r.text)
    assert "error" not in [e for e, _ in events], events
    dry = json.loads([m for m in fake_llm.calls[1] if m["role"] == "tool"][0]["content"])
    assert [t["id"] for t in dry["tradeoffs"]] == order

    cards = [d for e, d in events if e == "card"]
    assert [c["card_type"] for c in cards] == ["tradeoff"] * 3
    q = [c["props"]["question"] for c in cards]
    assert q[0] == f'Keeping "{a["name"]} and {b["name"]} work different shifts" costs $120 more this week. Keep it?'
    assert q[1] == f"Covering {role['name']} Tue 2 pm–4 pm needs 3 hours over your budget ($51). Approve the hours, or leave it open?"
    assert q[2] == f"Covering {role['name']} Sat 10 am–11:30 am needs 1.5 hours over your budget ($24.50). Approve the hours, or leave it open?"
    approve = next(o for o in cards[1]["props"]["options"] if o["id"].endswith(":approve"))
    assert approve["cost_dollars"] == 51 and "coverage 90.0% → 92.5%" in approve["effect"]

    cfg = StoreConfig.model_validate(client.get(f"/api/stores/{sid}/config").json())
    assert next(c for c in cfg.constraints if c.id == "c_apart").status.value == "rejected"  # dropped
    (ap,) = cfg.budget.approvals  # one approval: the approved gap's hours, by the leader
    assert (ap.extra_hours, ap.approved_by) == (3.0, "leader")
    assert tradeoffs.answered(client.app.state.db, sid) == {order[0]: "drop", order[1]: "approve", order[2]: "leave_open"}


def test_tradeoff_is_asked_once_and_ids_must_exist(client, built):
    sid, _, items, _, _ = built
    client.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 5})
    ctx = T.ToolContext(db=client.app.state.db, store_id=sid)
    assert "error" in T.ask_build_tradeoff(ctx, {"tradeoff_id": "nope"}).content
    card = T.ask_build_tradeoff(ctx, {"tradeoff_id": items[1]["id"]})
    assert card.apply({"option_id": f"{items[1]['id']}:keep"}).content["decision"] == "keep"
    assert "already answered" in T.ask_build_tradeoff(ctx, {"tradeoff_id": items[1]["id"]}).content["error"]
    summary = T.get_tradeoffs(ctx, {})
    assert [t["answered"] for t in summary["tradeoffs"]] == ["keep", None, None]
    # the approval gate still holds: approve_budget_increase without a card choice is refused
    assert "error" in T.approve_budget_increase(ctx, {"option_id": "made-up", "extra_hours": 99}).content
