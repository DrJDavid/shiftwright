"""The engine paths with a fake engine module: solve_week only (repair skips cleanly), then with
fix_day (repair is picked up automatically), and the side-by-side worked example."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from shiftwright_contracts.models import FixPlan
from shiftwright_evals.llm import CachedClient, MockClient
from shiftwright_evals.mock import MOCK_MODELS
from shiftwright_evals.report import build
from shiftwright_evals.runner import run_all
from shiftwright_evals.score import drop_callouts
from shiftwright_evals.suites import make_case
from shiftwright_evals.systems import BaselineSystem, ShiftwrightSystem


def fake_solve(config, time_limit_s=0):
    """A deterministic stand-in: an empty schedule."""
    from shiftwright_contracts.models import Schedule
    return Schedule(store_id=config.store.id, week_start=config.store.week_start,
                    config_version=config.config_version, produced_by="engine", status="feasible")


def fake_fix(req, time_limit_s=0):
    after = drop_callouts(req.schedule, req.callouts)
    return FixPlan(actions=[], outreach_queue=[], schedule_if_all_accept=after, schedule_if_none_accept=after,
                   coverage_before_pct=0, coverage_after_best_pct=0, coverage_after_worst_pct=0)


def _engine(tmp_path, with_fix: bool) -> ShiftwrightSystem:
    eng = ShiftwrightSystem(enabled=False, cache_dir=None)
    mod = SimpleNamespace(solve_week=fake_solve, **({"fix_day": fake_fix} if with_fix else {}))
    eng.mod, eng.src_hash, eng.unavailable_reason = mod, "fake", None
    return eng


def _run(tmp_path, eng, name):
    cases = [make_case("weekly", "S", "legal_trap", 1, "CA"), make_case("repair", "S", "normal", 1)]
    client = CachedClient(MockClient(), None)
    systems = [eng] + [BaselineSystem(m, client, mock=True) for m in MOCK_MODELS]
    run_dir = tmp_path / "runs" / name
    asyncio.run(run_all(cases, systems, run_dir, log=lambda *_: None))
    manifest = {"run_id": name, "quick": True, "mock_baselines": True, "suites": ["weekly", "repair"],
                "systems": [{"name": s.name, "available": s.available, "unavailable_reason": s.unavailable_reason}
                            for s in systems]}
    build(run_dir, tmp_path / "reports" / name, manifest)
    return json.loads((tmp_path / "reports" / name / "report.json").read_text()), \
        (tmp_path / "reports" / name / "report.html").read_text()


def test_repair_skips_cleanly_without_fix_day(tmp_path):
    report, html = _run(tmp_path, _engine(tmp_path, with_fix=False), "nofix")
    sw = {r["suite"]: r for r in report["rows"] if r["system"] == "shiftwright"}
    assert sw["weekly"]["outcome"] == "ok" and sw["repair"]["outcome"] == "unavailable"
    assert "no fix_day yet" in sw["repair"]["note"]
    base = json.loads((tmp_path / "runs" / "nofix" / "_inputs" / "repair-S-normal-TX-s1" / "repair.json").read_text())
    assert base["base_source"].startswith("engine returned no shifts")  # empty fake schedule -> history fallback
    # Baselines still run the repair suite.
    assert any(r["suite"] == "repair" and r["outcome"] == "ok" for r in report["rows"] if r["system"] != "shiftwright")


def test_repair_picked_up_with_fix_day_and_worked_example_side_by_side(tmp_path):
    report, html = _run(tmp_path, _engine(tmp_path, with_fix=True), "fix")
    rep = next(r for r in report["rows"] if r["system"] == "shiftwright" and r["suite"] == "repair")
    assert rep["outcome"] == "ok" and rep["callouts_still_working"] == 0 and rep["changes_before_now"] == 0
    # Worked example pairs a baseline with Shiftwright on the same scenario.
    key = report["worked_example"]
    assert key is not None
    ex = next((r for r in report["rows"] if r["key"] == key), None)
    assert ex is not None
    assert ex["scenario"] == "weekly-S-legal_trap-CA-s1"
    assert "Shiftwright: what the validator found" in html and "Same store, same inputs" in html
