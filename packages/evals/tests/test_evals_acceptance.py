"""WS5 acceptance tests (briefs/WS5-evals.md).

1. `eval-quick` runs end to end with --mock-baselines and no API key.
2. Re-running with the cache produces identical reports.
3. Report numbers match a manual recount from validation.json files for 2 sampled runs.
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from shiftwright_evals.cli import main


def _run(tmp: Path, run_id: str) -> int:
    return main([
        "--quick", "--mock-baselines", "--no-engine",
        "--out-dir", str(tmp / "runs"), "--reports-dir", str(tmp / "reports"),
        "--cache-dir", str(tmp / "cache"), "--run-id", run_id,
    ])


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("evals")
    env_key = os.environ.pop("OPENROUTER_API_KEY", None)
    try:
        assert _run(tmp, "rid-one") == 0
        assert _run(tmp, "rid-two") == 0
    finally:
        if env_key is not None:
            os.environ["OPENROUTER_API_KEY"] = env_key
    return tmp


def test_quick_cli_subprocess_no_api_key(tmp_path):
    """`make eval-quick` equivalent, in a fresh process with no key in the environment."""
    env = {k: v for k, v in os.environ.items() if k not in ("OPENROUTER_API_KEY", "BASELINE_MODELS")}
    proc = subprocess.run(
        [sys.executable, "-m", "shiftwright_evals", "--quick", "--mock-baselines", "--no-engine",
         "--out-dir", str(tmp_path / "runs"), "--reports-dir", str(tmp_path / "reports"),
         "--cache-dir", str(tmp_path / "cache"), "--run-id", "sub"],
        env=env, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "reports" / "sub" / "report.html").exists()


def test_quick_runs_end_to_end(two_runs):
    run_dir = two_runs / "runs" / "rid-one"
    report = json.loads((two_runs / "reports" / "rid-one" / "report.json").read_text())
    scenarios = {r["scenario"] for r in report["rows"]}
    assert len(scenarios) >= 10
    baseline_rows = [r for r in report["rows"] if r["system"].startswith("baseline:")]
    assert baseline_rows
    for r in baseline_rows:
        folder = run_dir / r["path"]
        for name in ("prompt.txt", "raw_output.txt", "schedule.json", "validation.json"):
            assert (folder / name).exists(), folder / name
    # Several kinds of canned failure show up.
    outcomes = Counter(r["outcome"] for r in baseline_rows)
    assert outcomes["truncated"] >= 1 and outcomes["unparseable"] >= 1 and outcomes["ok"] >= 1
    codes = Counter(c for r in baseline_rows for c in r["by_code"])
    assert codes["unknown_entity"] >= 1
    assert codes["minor_prohibited_role"] >= 1
    assert codes["budget_hours"] >= 1
    # False "feasible" on infeasible scenarios is caught by the honesty score.
    honesty = [r for r in baseline_rows if r["suite"] == "honesty"]
    assert any(r["honesty"] == "FN" for r in honesty)
    # Engine disabled -> shiftwright reported unavailable, not a crash.
    sw = [r for r in report["rows"] if r["system"] == "shiftwright"]
    assert sw and all(r["outcome"] == "unavailable" for r in sw)
    html = (two_runs / "reports" / "rid-one" / "report.html").read_text()
    assert "unavailable" in html and "<svg" in html and "Honesty" in html


def test_cached_rerun_is_identical(two_runs):
    a = (two_runs / "reports" / "rid-one" / "report.html").read_text().replace("rid-one", "RUN")
    b = (two_runs / "reports" / "rid-two" / "report.html").read_text().replace("rid-two", "RUN")
    assert a == b
    manifest = json.loads((two_runs / "runs" / "rid-two" / "manifest.json").read_text())
    assert manifest["llm_calls"]["misses"] == 0 and manifest["llm_calls"]["hits"] > 0


def test_report_numbers_match_recount(two_runs):
    run_dir = two_runs / "runs" / "rid-one"
    report = json.loads((two_runs / "reports" / "rid-one" / "report.json").read_text())
    html = (two_runs / "reports" / "rid-one" / "report.html").read_text()
    scored = [r for r in report["rows"] if r["outcome"] != "unavailable"]
    for row in random.Random(7).sample(scored, 2):
        val = json.loads((run_dir / row["path"] / "validation.json").read_text())
        hard = [v for v in val["violations"] if v["severity"] == "hard"]
        assert row["hard_count"] == len(hard) == val["hard_count"]
        assert row["by_code"] == dict(Counter(v["code"] for v in hard))
        assert row["coverage_pct"] == round(val["recomputed_metrics"]["coverage_pct"], 1)
        assert row["wage_cost"] == round(val["recomputed_metrics"]["total_wage_cost"], 2)
        metrics = val["recomputed_metrics"]
        assert row["real_cost"] == round(metrics["total_wage_cost"] + metrics["premium_pay_dollars"], 2)
        # Same numbers in the HTML all-runs table.
        m = re.search(r'<tr id="run-%s">(.*?)</tr>' % re.escape(row["key"]), html, re.S)
        assert m, row["key"]
        cells = re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S)
        text = [re.sub(r"<[^>]+>", "", c).strip() for c in cells]
        assert str(len(hard)) in text
        assert f"{row['coverage_pct']:.1f}" in text
