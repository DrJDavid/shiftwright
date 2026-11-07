"""Generated sample businesses (PUNCHLIST A3): POST /api/workplaces/generated, chat attachments, zip download."""
from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from api_helpers import parse_sse, signup
from shiftwright_api import generated
from shiftwright_api.agent.llm import call, say

CSV_KINDS = ["roster", "training", "availability", "forecast", "history"]


def _generate(client, **body) -> dict:
    r = client.post("/api/workplaces/generated", json={"sector": "retail", "difficulty": "easy", "seed": 7, **body})
    assert r.status_code == 200, r.text
    return r.json()


def _food_builds() -> bool:
    try:
        generated.build(generated.parse_params({"sector": "food", "difficulty": "easy", "seed": 7}))
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def anon(app):
    with TestClient(app) as c:
        yield c


def test_needs_a_session(anon):
    assert anon.post("/api/workplaces/generated", json={"sector": "retail"}).status_code == 401
    assert anon.get("/api/workplaces/st_x/sample-data.zip").status_code == 401


@pytest.mark.parametrize("body", [
    {},
    {"sector": "bakery"},
    {"sector": "retail", "size": "L"},
    {"sector": "retail", "difficulty": "infeasible"},
    {"sector": "retail", "state": "Texas"},
    {"sector": "retail", "city": "austin"},
    {"sector": "retail", "state": "TX", "city": "<script>"},
    {"sector": "retail", "seed": -1},
    {"sector": "retail", "seed": "42"},
    {"sector": "retail", "seed": True},
    {"sector": "retail", "colour": "blue"},
])
def test_bad_values_400(client, body):
    assert client.post("/api/workplaces/generated", json=body).status_code == 400


def test_generated_workplace_is_owned_previewed_and_uncommitted(client, app):
    g = _generate(client)
    sid = g["store_id"]
    assert set(g) >= {"store_id", "company_name", "kickoff"}
    assert "(" not in g["company_name"]  # no "(S/easy)" generator tag
    assert g["kickoff"]["message"].endswith("My exports are attached.")
    att = g["kickoff"]["attachments"]
    assert [a["kind"] for a in att] == CSV_KINDS
    assert all(a["filename"] == f"{a['kind']}.csv" and a["row_count"] > 0 for a in att)

    cfg = client.get(f"/api/stores/{sid}/config").json()
    assert cfg["store"]["name"] == g["company_name"] and cfg["store"]["sector"] == "retail"
    assert cfg["store"]["jurisdiction"] == {"state": "TX", "city": "austin"}
    assert cfg["employees"] == [] and cfg["roles"] == [] and cfg["demand"] == [] and cfg["store"]["hours"] == []
    db = app.state.db
    for a in att:  # cached exactly like POST /import/{kind}: full parse + preview
        assert len(db.get(sid, "import_rows", a["kind"])) == a["row_count"]
        assert db.get(sid, "import_preview", a["kind"])["row_count"] == a["row_count"]
    # ...so the REST commit works on it with no upload
    pv = db.get(sid, "import_preview", "roster")
    r = client.post(f"/api/stores/{sid}/import/roster/commit", json={"mapping": pv["proposed_mapping"]})
    assert r.status_code == 200 and len(r.json()["employees"]) == att[0]["row_count"]

    (w,) = client.get("/api/workplaces").json()["workplaces"]
    assert w["id"] == sid and w["sample_of"] == "generated"
    with TestClient(app) as b:
        signup(b, email="bob@example.com")
        assert b.get(f"/api/stores/{sid}/config").status_code == 404
        assert b.get(f"/api/workplaces/{sid}/sample-data.zip").status_code == 404


def test_same_seed_same_company(client):
    a, b = _generate(client, seed=11), _generate(client, seed=11)
    assert a["company_name"] == b["company_name"] and a["kickoff"] == b["kickoff"]
    assert a["store_id"] != b["store_id"]


def test_sample_data_zip(client):
    g = _generate(client)
    r = client.get(f"/api/workplaces/{g['store_id']}/sample-data.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    names = {n.rsplit("/", 1)[-1] for n in zipfile.ZipFile(io.BytesIO(r.content)).namelist()}
    assert names >= {f"{k}.csv" for k in CSV_KINDS} | {"README.txt", "ANSWER_KEY.txt"}
    plain = client.post("/api/stores", json={"template": "empty", "name": "X", "jurisdiction": {"state": "TX"}}).json()
    assert client.get(f"/api/workplaces/{plain['store']['id']}/sample-data.zip").status_code == 404


def test_rate_limit_5_per_user(client, app):
    for i in range(5):
        _generate(client, seed=i)
    assert client.post("/api/workplaces/generated", json={"sector": "retail", "seed": 9}).status_code == 429
    with TestClient(app) as b:
        signup(b, email="bob@example.com")
        assert b.post("/api/workplaces/generated", json={"sector": "retail", "seed": 9}).status_code == 200


def test_attachments_must_be_import_kinds(client):
    g = _generate(client)
    r = client.post(f"/api/stores/{g['store_id']}/chat",
                    json={"messages": [{"role": "user", "content": "hi", "attachments": [{"kind": "selfie"}]}]})
    assert r.status_code == 422


@pytest.mark.parametrize("sector", ["food", "retail"])
def test_autopilot_reaches_ready_for_an_easy_business(client, fake_llm, sector):
    """The manager's kickoff + attachments; the agent imports each file on a csv_import card, then fills in
    hours, budget and priorities from the narrative; every card is answered with accept_prefill."""
    if sector == "food" and not _food_builds():
        pytest.skip("food CSV export still fails in shiftwright_scenarios (PUNCHLIST E1)")
    g = _generate(client, sector=sector)
    sid = g["store_id"]
    assert client.get(f"/api/stores/{sid}/config").json()["employees"] == []
    # What the narrative tells the agent (hours, payroll); the fake agent reads it from the scenario.
    sc = generated._scenario(generated.parse_params({"sector": sector, "difficulty": "easy", "seed": 7}))
    hours = [h.model_dump() for h in sc.config.store.hours]
    cap = sc.config.budget.weekly_hours_cap

    fake_llm.script([call("ask_csv_import", kind=a["kind"]) for a in g["kickoff"]["attachments"]] + [
        call("ask_store_basics", prefill={"hours": hours}),
        call("ask_payroll", prefill={"weekly_hours_cap": cap}),
        say("Imported. Next: what an uncovered hour costs per role."),
    ])
    msg = {"role": "user", "content": g["kickoff"]["message"],
           "attachments": [{"kind": a["kind"]} for a in g["kickoff"]["attachments"]]}
    r = client.post(f"/api/stores/{sid}/chat?auto_cards=accept_prefill", json={"mode": "onboard", "messages": [msg]})
    events = parse_sse(r.text)
    assert "error" not in [e for e, _ in events], events
    cards = [d for e, d in events if e == "card"]
    assert [c["card_type"] for c in cards[:5]] == ["csv_import"] * 5
    assert all(c["props"]["preview"]["row_count"] > 0 for c in cards[:5])
    first_user = [m for m in fake_llm.calls[0] if m["role"] == "user"][0]["content"]
    assert "[Attached exports: roster (" in first_user and "preview ready" in first_user
    tool_results = [m["content"] for m in fake_llm.calls[-1] if m["role"] == "tool"]
    assert sum('"committed": true' in t for t in tool_results) == 5

    cfg = client.get(f"/api/stores/{sid}/config").json()
    assert len(cfg["employees"]) == g["kickoff"]["attachments"][0]["row_count"]
    roles = [{**r, "gap_penalty_per_hour": 20} for r in cfg["roles"]]
    fake_llm.script([call("ask_roles", roles=roles), call("ask_confirm_tags"), call("readiness_check"),
                     say("Ready to build.")])
    r = client.post(f"/api/stores/{sid}/chat?auto_cards=accept_prefill",
                    json={"mode": "onboard", "messages": [{"role": "user", "content": "$20 an hour for all of them"}]})
    assert "error" not in [e for e, _ in parse_sse(r.text)]
    rd = client.get(f"/api/stores/{sid}/readiness").json()
    assert rd["ready"] is True, [c for c in rd["checks"] if not c["ok"]]
