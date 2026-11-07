"""department_staffing card (API.md v1.3), equipment tagging, priorities readiness."""
from __future__ import annotations

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
    assert "Forklift Operator" in check["detail"] and "confirm" in check["detail"]
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
    assert checks["business_type"]["severity"] == "warn" and checks["business_type"]["ok"] is True
