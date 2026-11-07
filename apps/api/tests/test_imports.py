"""CSV import: preview (mapping proposed, nothing saved) -> commit (deterministic parse)."""
from __future__ import annotations

from api_helpers import make_store
from shiftwright_contracts.models import StoreConfig

from shiftwright_api.models import ImportPreview

ROSTER = """TM_ID,Team Member,Dept,Wage Rate,DOB,Cell,Emp Type,Hire Date,Skills
1001,Jordan Lee,Front of Store,$16.50,2001-04-02,(512) 555-0101,PT,2023-05-01,Cashier;Drive Up
1002,Casey Ng,Front of Store,$17.00,1999-09-12,512-555-0102,FT,2022-01-10,Cashier
1003,Riley Park,Receiving,$18.25,2009-01-15,5125550103,PT,2025-06-01,Truck Unload;Forklift
"""

FORECAST = """Workload,Date,Interval,Required Staff
Cashier,Mon,08:00,2
Cashier,Mon,08:30,2
Cashier,Mon,09:00,3
Leader on Duty,Mon,08:00-22:00,1
"""

AVAIL = """TM_ID,Avail Mon,Avail Tue,Avail Sat
1001,08:00-14:00,OFF,
"""


def _upload(client, sid, kind, text):
    r = client.post(f"/api/stores/{sid}/import/{kind}", files={"file": (f"{kind}.csv", text, "text/csv")})
    assert r.status_code == 200, r.text
    return ImportPreview.model_validate(r.json())


def _commit(client, sid, kind, pv, rows=None):
    r = client.post(f"/api/stores/{sid}/import/{kind}/commit",
                    json={"mapping": pv.proposed_mapping, "rows": rows if rows is not None else pv.rows_preview})
    assert r.status_code == 200, r.text
    return StoreConfig.model_validate(r.json())


def test_roster_preview_then_commit(client):
    cfg0 = make_store(client, template="bigbox_mid")
    sid = cfg0["store"]["id"]
    pv = _upload(client, sid, "roster", ROSTER)
    assert pv.row_count == 3
    assert pv.proposed_mapping["TM_ID"] == "employee_id"
    assert pv.proposed_mapping["Wage Rate"] == "wage_per_hour"
    assert pv.proposed_mapping["Dept"] == "home_department"
    assert pv.unmapped_required == []
    assert "wage_per_hour" in pv.target_fields and set(pv.proposed_mapping.values()) - {None} <= set(pv.target_fields)
    assert set(pv.required_fields) == {"employee_id", "name", "home_department", "wage_per_hour"}
    rules = {r["need"]: r["any_of"] for r in pv.required_any_of}
    assert ["first_name", "last_name"] in rules["name"] and rules["age"] == [["age"], ["birth_date"]]
    mapped = {v for v in pv.proposed_mapping.values() if v}
    assert [n for n, alts in rules.items() if not any(set(a) <= mapped for a in alts)] == pv.unmapped_required
    # nothing saved yet
    assert client.get(f"/api/stores/{sid}/config").json()["employees"] == []

    cfg = _commit(client, sid, "roster", pv)
    assert cfg.config_version == cfg0["config_version"] + 1
    by_id = {e.id: e for e in cfg.employees}
    assert by_id["1001"].phone == "+15125550101"
    assert by_id["1001"].wage_per_hour == 16.5
    assert by_id["1002"].status.value == "full_time"
    assert set(by_id["1001"].trained_role_ids) == {"cashier", "drive_up"}
    assert by_id["1003"].age == 16 or by_id["1003"].age == 17
    # unknown role name gets added as a flagged default
    forklift = next(r for r in cfg.roles if r.id == "forklift")
    assert "review" in forklift.description


def test_forecast_and_availability(client):
    sid = make_store(client, template="bigbox_small")["store"]["id"]
    _commit(client, sid, "roster", _upload(client, sid, "roster", ROSTER))
    cfg = _commit(client, sid, "forecast", _upload(client, sid, "forecast", FORECAST))
    cash = sorted((d.start, d.end, d.headcount) for d in cfg.demand if d.role_id == "cashier")
    assert cash == [(480, 540, 2), (540, 570, 3)]
    lod = [d for d in cfg.demand if d.role_id == "leader_on_duty"]
    assert (lod[0].start, lod[0].end) == (480, 1320)

    cfg = _commit(client, sid, "availability", _upload(client, sid, "availability", AVAIL))
    av = next(e for e in cfg.employees if e.id == "1001").availability
    assert {(a.weekday, a.start, a.end) for a in av} == {(0, 0, 480), (0, 840, 1440), (1, 0, 1440)}


def test_commit_with_unmapped_required_rejected(client):
    sid = make_store(client)["store"]["id"]
    pv = _upload(client, sid, "roster", "Foo,Bar\n1,2\n")
    assert "employee_id" in pv.unmapped_required
    r = client.post(f"/api/stores/{sid}/import/roster/commit", json={"mapping": pv.proposed_mapping, "rows": pv.rows_preview})
    assert r.status_code == 422
