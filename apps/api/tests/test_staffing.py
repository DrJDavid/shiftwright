"""department_staffing card (API.md v1.3), equipment tagging, priorities readiness."""
from __future__ import annotations

import pytest

from api_helpers import make_store, parse_sse, tiny_config
from shiftwright_api.agent.llm import call, say
from shiftwright_api.agent.tools import staffing_to_demand
from shiftwright_contracts.models import StoreConfig


def _store_8_to_22():
    cfg = tiny_config().model_copy(deep=True)
    cfg.store.hours = [h.model_copy(update={"open": 480, "close": 1320}) for h in cfg.store.hours]
    cfg.store.slot_minutes = 30
    return cfg


def test_staffing_conversion():
    cfg = _store_8_to_22()
    days = sorted({h.day for h in cfg.store.hours if h.close > h.open})
    reqs = staffing_to_demand(cfg, {"cashier": {
        "base": 2, "peaks": [{"day_group": "weekday", "start": 1020, "end": 1200, "headcount": 4}],
        "open": {"headcount": 1, "minutes_before_open": 60}, "close": {"headcount": 1, "minutes_after_close": 30}}})
    wd = next(d for d in days if d < 5)
    got = sorted((r["start"], r["end"], r["headcount"]) for r in reqs if r["day"] == wd)
    assert got == [(420, 480, 1), (480, 1020, 2), (1020, 1200, 4), (1200, 1320, 2), (1320, 1350, 1)]
    assert all(r["source"] == "leader" for r in reqs)
    if 5 in days:  # peak is weekday-only
        assert sorted((r["start"], r["end"], r["headcount"]) for r in reqs if r["day"] == 5) == \
            [(420, 480, 1), (480, 1320, 2), (1320, 1350, 1)]


def test_staffing_card_flow(client, fake_llm):
    sid = make_store(client)["store"]["id"]
    cfg = _store_8_to_22()
    cfg.store.id = sid
    client.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json"))
    dept = next(r.department_id for r in cfg.roles if r.id == "cashier")
    fake_llm.script([call("ask_department_staffing", department_id=dept,
                          prefill={"cashier": {"peaks": [{"day_group": "weekday", "start": 1020, "end": 1200,
                                                          "headcount": 4}]}}),
                     call("show_coverage_preview", day_type="weekday"), say("Saved.")])
    script = {"department_staffing": [{"staffing": {"cashier": {"base": 1, "peaks": [], "open": None, "close": None}}}]}
    events = parse_sse(client.post(f"/api/stores/{sid}/chat?auto_cards=scripted", json={
        "mode": "onboard", "messages": [{"role": "user", "content": "x"}], "card_script": script}).text)
    cards = [d for e, d in events if e == "card"]
    staffing = cards[0]["props"]
    assert "Not a forecast" in staffing["suggestion_note"] and staffing["from_chat"] == ["cashier"]
    assert staffing["suggested"]["cashier"]["peaks"][0]["headcount"] == 4
    assert cards[1]["card_type"] == "coverage_grid" and cards[1]["props"]["readonly"] is True
    new = StoreConfig.model_validate(client.get(f"/api/stores/{sid}/config").json())
    cash = [d for d in new.demand if d.role_id == "cashier" and d.source.value != "event"]
    assert cash and all(d.headcount == 1 and d.source.value == "leader" for d in cash)
    assert events[-1] == ("done", {})


def test_imported_forklift_role_is_tagged_and_reviewable(client):
    sid = make_store(client, template="empty")["store"]["id"]
    roster = ("ID,Name,Dept,Wage,Age,Phone,Skills\n"
              "1,Ann Adult,Receiving,$18,30,5125550101,Forklift Operator\n"
              "2,Kid Teen,Receiving,$15,16,5125550102,Forklift Operator\n")
    r = client.post(f"/api/stores/{sid}/import/roster", files={"file": ("r.csv", roster.encode(), "text/csv")})
    pv = r.json()
    r = client.post(f"/api/stores/{sid}/import/roster/commit", json={"mapping": pv["proposed_mapping"], "rows": pv["rows_preview"]})
    assert r.status_code == 200, r.text
    assert r.json()["role_tags"]["forklift_operator"] == ["powered_industrial_truck"]
    assert int(r.headers["X-Import-Warning-Count"]) >= 1
    w = client.get(f"/api/stores/{sid}/import/roster/warnings").json()["warnings"]
    assert any("powered_industrial_truck" in x for x in w)
    check = next(c for c in client.get(f"/api/stores/{sid}/readiness").json()["checks"] if c["id"] == "equipment_roles")
    # "Forklift Operator" names the work outright: the tag is kept without asking (still removable)
    assert "Forklift Operator" in check["detail"] and check["severity"] == "ok"
    r = client.post(f"/api/stores/{sid}/equipment_roles", json={"role_id": "forklift_operator", "decision": "reject"})
    assert "forklift_operator" not in r.json()["role_tags"]
    # a rejected role is not re-tagged by the next import
    client.post(f"/api/stores/{sid}/import/roster", files={"file": ("r.csv", roster.encode(), "text/csv")})
    r = client.post(f"/api/stores/{sid}/import/roster/commit", json={"mapping": pv["proposed_mapping"], "rows": pv["rows_preview"]})
    assert "forklift_operator" not in r.json()["role_tags"]


def test_chat_created_equipment_role_is_tagged(client, fake_llm):
    sid = make_store(client, template="bigbox_small")["store"]["id"]
    fake_llm.script([call("upsert_role", role={"id": "reach_truck", "department_id": "grocery", "name": "Reach Truck",
                                               "gap_penalty_per_hour": 20}), say("ok")])
    client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "x"}]})
    assert client.get(f"/api/stores/{sid}/config").json()["role_tags"]["reach_truck"] == ["powered_industrial_truck"]
    tool_msg = [m for m in fake_llm.calls[-1] if m["role"] == "tool"][0]["content"]
    assert "equipment_tagged" in tool_msg


def test_looks_powered():
    from shiftwright_api.equipment import looks_powered
    for name in ("FORKLIFT", "PIT Operator", "Reach Truck", "Electric Pallet Jack", "Order Picker Lift", "Hi-Lo"):
        assert looks_powered("x", name), name
    for name in ("Cashier", "Order Picker", "Pallet Jack", "Shelf Stacker", "Truck Unload", "Spirit Team"):
        assert not looks_powered("x", name), name


def test_priorities_block_readiness(client):
    sid = make_store(client)["store"]["id"]
    cfg = tiny_config().model_copy(deep=True)
    cfg.store.id = sid
    for r in cfg.roles:
        if r.id == "cashier":
            r.gap_penalty_per_hour = 0
    client.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json"))
    rd = client.get(f"/api/stores/{sid}/readiness").json()
    check = next(c for c in rd["checks"] if c["id"] == "priorities")
    assert rd["ready"] is False and not check["ok"] and "Cashier" in check["detail"]



def test_tags_for_all_role_tags():
    from shiftwright_api.equipment import tags_for
    cases = {"Fry Cook": {"fryer", "cooking"}, "Line Cook": {"cooking"}, "Deli Slicer": {"meat_slicer"},
             "Bartender": {"alcohol_service"}, "Delivery Driver": {"motor_vehicle_driving"},
             "Bakery Mixer": {"bakery_machine"}, "Baler Operator": {"baler_compactor"}, "Lumber Saw": {"power_saw"},
             "Ladder Stocker": {"ladder_scaffold"}, "Forklift": {"powered_industrial_truck"},
             "Server": set(), "Host": set(), "Dishwasher": set(), "Drive Up": set(), "Barista": set(),
             "Prep": set(), "Cashier": set()}
    for name, want in cases.items():
        assert set(tags_for("x", name)) == want, name


def test_minors_on_tagged_roles_and_business_type_warn(client):
    sid = make_store(client)["store"]["id"]
    cfg = tiny_config().model_copy(deep=True)
    cfg.store.id = sid
    cfg.store.sector = None
    role = cfg.roles[0]
    cfg.role_tags[role.id] = ["fryer"]
    kid = cfg.employees[0]
    kid.age = 15
    kid.trained_role_ids = list({*kid.trained_role_ids, role.id})
    client.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json"))
    rd = client.get(f"/api/stores/{sid}/readiness").json()
    checks = {c["id"]: c for c in rd["checks"]}
    assert checks["minors_on_tagged_roles"]["severity"] == "warn" and kid.name in checks["minors_on_tagged_roles"]["detail"]
    pack = client.get("/api/laws/resolve", params={"state": cfg.store.jurisdiction.state}).json()
    fryer_ban = [r["id"] for r in pack["rules"] if r["type"] == "minor_prohibited_roles"
                 and "fryer" in r["params"].get("role_tags", [])
                 and (r["params"].get("age_min") or 0) <= 15 < r["params"]["age_below"]]
    for rid in fryer_ban:
        assert f"barred by {rid}" in checks["minors_on_tagged_roles"]["detail"]
    assert checks["business_type"]["severity"] == "warn" and checks["business_type"]["ok"] is True


def test_tipped_wage_checked_against_full_minimum_without_tip_rule(client):
    sid = make_store(client)["store"]["id"]
    cfg = tiny_config().model_copy(deep=True)
    cfg.store.id = sid
    role = cfg.roles[0]
    role.tipped = True
    e = next(x for x in cfg.employees if role.id in x.trained_role_ids)
    e.tipped_wage_per_hour = 2.13
    client.put(f"/api/stores/{sid}/config", json=cfg.model_dump(mode="json"))
    check = next(c for c in client.get(f"/api/stores/{sid}/readiness").json()["checks"] if c["id"] == "minimum_wage")
    pack = client.get("/api/laws/resolve", params={"state": cfg.store.jurisdiction.state}).json()
    has_tip_rule = any(r["type"] == "tipped_minimum_wage" for r in pack["rules"])
    if not has_tip_rule:
        assert not check["ok"] and e.name in check["detail"] and "full minimum applies" in check["detail"]


def test_closed_days_dropped_and_chat_employee_defaults(client, fake_llm):
    from shiftwright_api.agent.llm import call, say
    sid = make_store(client, template="bigbox_small")["store"]["id"]
    fake_llm.script([call("set_store_basics", fields={"hours": [{"day": 0, "closed": True},
                                                                 {"day": 1, "open": 660, "close": 1260}],
                                                       "sector": "food", "business_description": "taqueria"}),
                     call("upsert_employee", employee={"id": "kevin", "name": "Kevin Ng", "age": 15,
                                                       "phone": "312-555-0109", "wage_per_hour": 17.1,
                                                       "trained_role_ids": ["cashier"]}),
                     say("ok")])
    client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "x"}]})
    cfg = client.get(f"/api/stores/{sid}/config").json()
    assert cfg["store"]["hours"] == [{"day": 1, "open": 660, "close": 1260}] and cfg["store"]["sector"] == "food"
    kev = cfg["employees"][0]
    assert kev["phone"] == "+13125550109" and kev["status"] == "part_time" and kev["home_department_id"]


def test_confirm_tags_card_is_the_only_way(client, fake_llm):
    from shiftwright_api.agent.llm import call, say
    sid = make_store(client, template="bigbox_small")["store"]["id"]
    # unclear names (a station, a place), so the owner is asked; clear titles are kept without a card
    fake_llm.script([call("upsert_role", role={"id": "fry_cook", "department_id": "grocery", "name": "Fry Station",
                                               "gap_penalty_per_hour": 20}),
                     call("upsert_role", role={"id": "bartender", "department_id": "grocery", "name": "Bar",
                                               "gap_penalty_per_hour": 20}),
                     call("ask_confirm_tags"), say("ok")])
    script = {"confirm_tags": [{"decisions": {"fry_cook": "keep", "bartender": "remove"}}]}
    events = parse_sse(client.post(f"/api/stores/{sid}/chat?auto_cards=scripted", json={
        "mode": "onboard", "messages": [{"role": "user", "content": "keep both"}], "card_script": script}).text)
    card = next(d for e, d in events if e == "card")
    assert card["card_type"] == "confirm_tags"
    assert {r["role_id"] for r in card["props"]["roles"]} == {"fry_cook", "bartender"}  # one card, every pending tag
    cfg = client.get(f"/api/stores/{sid}/config").json()
    assert set(cfg["role_tags"]["fry_cook"]) == {"fryer", "cooking"} and "bartender" not in cfg["role_tags"]
    check = next(c for c in client.get(f"/api/stores/{sid}/readiness").json()["checks"] if c["id"] == "equipment_roles")
    assert check["severity"] == "ok"  # nothing left pending
    assert "review_equipment_role" not in fake_llm.tools_seen


def test_agent_cannot_confirm_rules(client, fake_llm):
    from shiftwright_api.agent.llm import call, say
    sid = make_store(client)["store"]["id"]
    fake_llm.script([call("add_constraint", constraint={"id": "c1", "kind": "min_shift_length", "params": {"minutes": 240},
                                                        "strength": "hard", "status": "confirmed", "source": "leader"}),
                     call("set_constraint_status", constraint_id="c1", status="confirmed"), say("ok")])
    client.post(f"/api/stores/{sid}/chat", json={"mode": "onboard", "messages": [{"role": "user", "content": "x"}]})
    c = client.get(f"/api/stores/{sid}/config").json()["constraints"][0]
    assert c["status"] == "provisional"
    tool_msgs = [m["content"] for m in fake_llm.calls[-1] if m["role"] == "tool"]
    assert "Only the leader confirms" in tool_msgs[-1]


@pytest.mark.parametrize("name,tag,clear", [
    ("Line Cook", "cooking", True), ("Bartender", "alcohol_service", True), ("Forklift Operator", "powered_industrial_truck", True),
    ("Delivery Driver", "motor_vehicle_driving", True), ("Butcher", "meat_slicer", True),
    ("Fryer Cook", "cooking", True), ("Fryer Cook", "fryer", True),
    ("Deli", "meat_slicer", False), ("Bar", "alcohol_service", False), ("Delivery", "motor_vehicle_driving", False),
    ("Bakery Associate", "bakery_machine", False), ("Grill", "cooking", False), ("Dish / Prep", "cooking", False),
])
def test_clear_job_titles_skip_the_question(name, tag, clear):
    from shiftwright_api import equipment
    assert equipment.clear_tag(name, tag) is clear


def test_only_unclear_tags_are_left_for_the_owner(client):
    from shiftwright_api import equipment
    sid = make_store(client, template="tiny")["store"]["id"]
    db = client.app.state.db
    status = equipment.record_auto(db, sid, [("cook", "Line Cook", ["cooking"]), ("deli", "Deli", ["meat_slicer"])])
    assert status == {"cook": "clear", "deli": "auto"}
    assert equipment.pending(db, sid) == ["deli"]
