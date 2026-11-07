"""Drive the real API (create_app + TestClient, no server, no LLM) through a pack's CSV imports.

Used by test_packs.py, and runnable for a human-readable summary:

    uv run python packages/scenarios/import_packs/packs_harness.py [pack ...]

Flow per pack (the order a leader would use in the UI):
  1. POST /api/stores (template from leader_setup.json, normally "empty")
  2. PUT config: store basics the leader gives the store_basics card (hours, slot, timezone, week start)
  3. for each CSV: POST /import/{kind} -> preview; commit with the proposed mapping, overridden only by
     the pack's documented `manual_mappings` (what the leader fixes by hand in the mapping table);
     the commit sends only rows_preview, exactly like CsvImportCard does
  4. PUT config: payroll cap + role priorities (gap $/h) the leader confirms in chat
  5. GET /readiness, then POST /solve (time_limit_s 20)
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

from fastapi.testclient import TestClient

from shiftwright_api import imports
from shiftwright_api.main import create_app
from shiftwright_api.settings import Settings

HERE = Path(__file__).resolve().parent
KINDS = ["roster", "training", "availability", "forecast", "history"]
WEEK_START = "2026-11-09"


@dataclass
class ImportResult:
    kind: str
    status: int
    preview: dict
    mapping: dict
    commit_status: Optional[int] = None
    commit_detail: Any = None
    warnings: list[str] = field(default_factory=list)  # commit-time warnings (server-side only, see README)


class Session:
    def __init__(self, tmpdir: Optional[str] = None):
        self.tmp = tmpdir or tempfile.mkdtemp(prefix="csvpacks_")
        settings = Settings(database_url=f"sqlite:///{self.tmp}/packs.db", messenger="mock",
                            agent_model="fake/model", openrouter_api_key="")
        self.app = create_app(settings=settings)
        self.client = TestClient(self.app)
        self.sid = ""

    # ------------------------------------------------------------------ store
    def create(self, setup: dict) -> dict:
        r = self.client.post("/api/stores", json={"template": setup.get("template", "empty"), "name": setup["name"],
                                                   "jurisdiction": setup["jurisdiction"]})
        r.raise_for_status()
        cfg = r.json()
        self.sid = cfg["store"]["id"]
        return cfg

    def config(self) -> dict:
        return self.client.get(f"/api/stores/{self.sid}/config").json()

    def put(self, cfg: dict) -> dict:
        r = self.client.put(f"/api/stores/{self.sid}/config", json=cfg)
        assert r.status_code == 200, r.text
        return r.json()

    def store_basics(self, setup: dict) -> dict:
        cfg = self.config()
        h = setup["hours"]
        o, c = imports.parse_time(h["open"]), imports.parse_time(h["close"])
        cfg["store"].update({
            "week_start": WEEK_START, "timezone": setup["timezone"], "slot_minutes": setup["slot_minutes"],
            "hours": [{"day": d, "open": o, "close": c} for d in range(7)],
            "pre_open_minutes": setup.get("pre_open_minutes", 60),
            "post_close_minutes": setup.get("post_close_minutes", 60),
        })
        return self.put(cfg)

    def priorities_and_budget(self, setup: dict) -> dict:
        cfg = self.config()
        cfg["budget"]["weekly_hours_cap"] = setup["weekly_hours_cap"]
        pens = setup.get("gap_penalty_per_hour", {})
        for r in cfg["roles"]:
            if r["id"] in pens:
                r["gap_penalty_per_hour"] = pens[r["id"]]
        truck = setup.get("truck_days")
        if truck:
            s, e = imports.parse_time(truck["start"]), imports.parse_time(truck["end"])
            cfg["events"] = [{"id": f"truck_{d}", "kind": "truck", "day": imports.DAY_NAMES[d.lower()],
                              "start": s, "end": e, "note": "Truck day (leader)"} for d in truck["days"]]
        return self.put(cfg)

    # ------------------------------------------------------------------ import
    def preview(self, kind: str, path: Path) -> tuple[int, dict]:
        r = self.client.post(f"/api/stores/{self.sid}/import/{kind}",
                             files={"file": (path.name, path.read_bytes(), "text/csv")})
        return r.status_code, r.json()

    def commit(self, kind: str, mapping: dict, rows: list) -> tuple[int, Any, list[str]]:
        r = self.client.post(f"/api/stores/{self.sid}/import/{kind}/commit", json={"mapping": mapping, "rows": rows})
        # Commit-time warnings are stored server-side but NOT returned by the API (see README bug list),
        # so read them from the kv table directly.
        warnings = self.app.state.db.get(self.sid, "import_warnings", kind) or [] if r.status_code == 200 else []
        return r.status_code, r.json(), warnings

    def import_file(self, kind: str, path: Path, overrides: Optional[dict] = None) -> ImportResult:
        status, pv = self.preview(kind, path)
        res = ImportResult(kind=kind, status=status, preview=pv, mapping={})
        if status != 200:
            return res
        mapping = dict(pv["proposed_mapping"])
        mapping.update(overrides or {})
        res.mapping = mapping
        res.commit_status, res.commit_detail, res.warnings = self.commit(kind, mapping, pv["rows_preview"])
        return res

    # ------------------------------------------------------------------ checks
    def readiness(self) -> dict:
        return self.client.get(f"/api/stores/{self.sid}/readiness").json()

    def solve(self, time_limit_s: int = 20) -> dict:
        r = self.client.post(f"/api/stores/{self.sid}/solve", json={"time_limit_s": time_limit_s})
        assert r.status_code == 200, r.text
        return r.json()


def load_setup(pack: str) -> dict:
    return json.loads((HERE / pack / "leader_setup.json").read_text())


def run_pack(pack: str, session: Optional[Session] = None) -> tuple[Session, dict[str, ImportResult]]:
    """Steps 1-4 for a pack. Returns the session and the per-kind import results."""
    setup = load_setup(pack)
    s = session or Session()
    s.create(setup)
    s.store_basics(setup)
    manual = setup.get("manual_mappings", {})
    results = {}
    for kind in KINDS:
        p = HERE / pack / f"{kind}.csv"
        if p.exists():
            results[kind] = s.import_file(kind, p, manual.get(kind))
    s.priorities_and_budget(setup)
    return s, results


def failing_checks(readiness: dict) -> dict[str, str]:
    return {c["id"]: c["detail"] for c in readiness["checks"] if not c["ok"]}


def summarize(solved: dict) -> dict:
    sch, val = solved["schedule"], solved["validation"]
    m = sch.get("metrics") or {}
    return {"status": sch["status"], "shifts": len(sch["shifts"]), "gaps": len(sch["gaps"]),
            "coverage_pct": m.get("coverage_pct"), "hours": m.get("total_hours"),
            "validator_passed": val["passed"], "hard_violations": val["hard_count"],
            "violation_codes": sorted({v["code"] for v in val["violations"] if v["severity"] == "hard"})}


def role_assignments(solved: dict, role_id: str) -> set[str]:
    return {sh["employee_id"] for sh in solved["schedule"]["shifts"] for seg in sh["segments"]
            if seg["role_id"] == role_id}


if __name__ == "__main__":
    packs = sys.argv[1:] or ["clean_small_tx", "corporate_mid_tx", "messy_mid_ca"]
    for pack in packs:
        s, res = run_pack(pack)
        print(f"\n=== {pack} ===")
        for k, r in res.items():
            print(f"  {k}: preview {r.status} rows={r.preview.get('row_count')} "
                  f"unmapped={r.preview.get('unmapped_required')} commit={r.commit_status} "
                  f"warnings={len(r.warnings)}")
            for w in r.warnings[:12]:
                print("     -", w)
            if r.commit_status not in (200, None):
                print("     detail:", str(r.commit_detail)[:300])
        cfg = s.config()
        print(f"  employees={len(cfg['employees'])} roles={[x['id'] for x in cfg['roles']]} demand={len(cfg['demand'])}")
        print("  readiness failing:", failing_checks(s.readiness()))
        print("  solve:", summarize(s.solve()))
