"""The manager's journey from raw corporate exports to a usable week, with no LLM and no hand-made mappings.

What a manager does: create an empty workplace, tell it the hours and the hours budget (what the chat would
collect), drop in their CSV exports and accept the importer's proposed column mappings as-is, then build.
Scored against the scenario's hidden true config, like the realistic eval. This test exists because the
first real realistic run scheduled nobody: forecast job codes (GROC, CASH, LOD) became new roles nobody
was trained for, and imported roles had a $0 priority.
"""
from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from shiftwright_contracts.models import Schedule
from shiftwright_evals.realistic import export_texts, map_built_schedule
from shiftwright_evals.suites import make_case
from shiftwright_validator import validate

CASES = [
    ("S", "normal", "TX", "retail"),
    ("S", "legal_trap", "CA", "retail"),
    ("S", "normal", "IL/chicago", "food"),
]


def _in_built_ids(con: dict, truth, built: dict) -> dict:
    """A rule the manager states in their own words lands on the imported ids (TM_ID people, the export's roles)."""
    from shiftwright_api.imports import norm, role_aliases
    from shiftwright_scenarios.exports import JOB_CODES, tm_id

    names = {r.id: r.name for r in truth.roles}

    def role(rid: str) -> str:
        want = {norm(rid), norm(names.get(rid, rid)), norm(JOB_CODES.get(rid, rid))}
        for r in built["roles"]:
            if want & {norm(r["id"]), norm(r["name"]), *(norm(a) for a in role_aliases(r))}:
                return r["id"]
        return rid

    emp = {e.id: tm_id(e.id) for e in truth.employees}
    p = dict(con.get("params") or {})
    for k in ("role_id",):
        if k in p:
            p[k] = role(p[k])
    for k in ("employee_id",):
        if k in p:
            p[k] = emp.get(p[k], p[k])
    if "employee_ids" in p:
        p["employee_ids"] = [emp.get(x, x) for x in p["employee_ids"]]
    con = {**con, "params": p}
    if con.get("applies_to_employee_ids"):
        con["applies_to_employee_ids"] = [emp.get(x, x) for x in con["applies_to_employee_ids"]]
    return con


def _journey(case, tmp_path, training_role_column=None):
    import shiftwright_api.main as main_mod
    from shiftwright_api.settings import Settings

    settings = dataclasses.replace(Settings.from_env(), database_url=f"sqlite:///{tmp_path}/j.db", demo_key="",
                                   messenger="mock", openrouter_api_key="")
    if hasattr(settings, "auth_required"):
        settings = dataclasses.replace(settings, auth_required=False)
    truth = case.config
    with TestClient(main_mod.create_app(settings)) as c:
        sid = c.post("/api/stores", json={"template": "empty", "name": truth.store.name,
                                          "jurisdiction": truth.store.jurisdiction.model_dump()}).json()["store"]["id"]
        cfg = c.get(f"/api/stores/{sid}/config").json()
        # what the manager tells the chat (none of it is in the CSVs): hours, week, slot size, the hours
        # budget, and their rules ("nobody works more than 5 days", "no shifts under 4 hours")
        for k in ("hours", "week_start", "slot_minutes", "pre_open_minutes", "post_close_minutes", "max_shifts_per_day"):
            cfg["store"][k] = truth.store.model_dump(mode="json")[k]
        cfg["budget"] = truth.budget.model_dump(mode="json")
        cfg["constraints"] = []  # set after the imports, in the store's own ids (below)
        assert c.put(f"/api/stores/{sid}/config", json=cfg).status_code == 200
        for kind, text in export_texts(case).items():
            pv = c.post(f"/api/stores/{sid}/import/{kind}", files={"file": (f"{kind}.csv", text.encode(), "text/csv")})
            assert pv.status_code == 200, (kind, pv.text[:300])
            mapping = dict(pv.json()["proposed_mapping"])
            if kind == "training" and training_role_column:
                # the column an LLM mapper picked in the first real run: the title, while forecasts use the code
                mapping = {c: (None if f == "role" else f) for c, f in mapping.items()}
                mapping[training_role_column] = "role"
            cm = c.post(f"/api/stores/{sid}/import/{kind}/commit", json={"mapping": mapping})
            assert cm.status_code == 200, (kind, cm.text[:300])
        built = c.get(f"/api/stores/{sid}/config").json()
        built["constraints"] = [_in_built_ids(con.model_dump(mode="json"), truth, built) for con in truth.constraints]
        assert c.put(f"/api/stores/{sid}/config", json=built).status_code == 200
        built = c.get(f"/api/stores/{sid}/config").json()
        solved = c.post(f"/api/stores/{sid}/solve", json={"time_limit_s": 30}).json()
    return built, solved


@pytest.mark.parametrize("training_role_column", [None, "Job Desc"], ids=["proposed-mapping", "title-column"])
@pytest.mark.parametrize("size,difficulty,jur,sector", CASES)
def test_raw_exports_to_a_usable_week(size, difficulty, jur, sector, training_role_column, tmp_path):
    case = make_case("journey", size, difficulty, 1, jur, sector)
    built, solved = _journey(case, tmp_path, training_role_column)

    demanded = {d["role_id"] for d in built["demand"] if d["headcount"] > 0}
    trained = {r for e in built["employees"] for r in e["trained_role_ids"]}
    roles = {r["id"]: r for r in built["roles"]}
    nobody = sorted(demanded - trained)
    assert not nobody, f"staffing demand on roles nobody is trained for (duplicate roles from codes?): {nobody}"
    unpriced = sorted(r for r in demanded if roles[r]["gap_penalty_per_hour"] <= 0)
    assert not unpriced, f"roles with demand but no priority: {unpriced}"
    assert len(built["roles"]) <= len(case.config.roles) + 2, (
        f"{len(built['roles'])} roles imported for a store with {len(case.config.roles)}: duplicates")

    sched = solved["schedule"]
    assert sched["shifts"], "the week came back empty"
    cov = (sched.get("metrics") or {}).get("coverage_pct") or 0
    assert cov >= 60, f"coverage {cov}%"

    mapped = Schedule(**map_built_schedule(sched, built, case.config))
    report = validate(case.config, mapped)
    hard = [v for v in report.violations if v.severity == "hard"]
    assert not hard, f"{len(hard)} hard violations vs the true store: {[(v.code.value, v.message[:80]) for v in hard[:5]]}"
