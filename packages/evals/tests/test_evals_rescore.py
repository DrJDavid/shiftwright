"""--rescore-from: reuse a previous run's baseline replies by scenario id + model, no API calls."""
from __future__ import annotations

import json

from shiftwright_evals.cli import main


def _args(tmp, *extra):
    return ["--quick", "--no-engine", "--out-dir", str(tmp / "runs"), "--reports-dir", str(tmp / "reports"),
            "--cache-dir", str(tmp / "cache"), *extra]


def test_rescore_reuses_replies_and_lists_changed_stores(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(_args(tmp_path, "--mock-baselines", "--run-id", "old")) == 0
    # Pretend one store's roster changed since the old run: that reply must not be reused.
    cfg_path = tmp_path / "runs" / "old" / "_inputs" / "weekly-S-easy-TX-s1" / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["employees"][0]["id"] = "e_renamed"
    cfg_path.write_text(json.dumps(cfg))

    assert main(_args(tmp_path, "--rescore-from", "old", "--run-id", "new")) == 0
    old = {r["key"]: r for r in json.loads((tmp_path / "reports" / "old" / "report.json").read_text())["rows"]}
    new = json.loads((tmp_path / "reports" / "new" / "report.json").read_text())
    manifest = json.loads((tmp_path / "runs" / "new" / "manifest.json").read_text())
    assert manifest["llm_calls"] == {"hits": 0, "misses": 0}
    assert set(manifest["not_rescored"]) == {"baseline:mock-a", "baseline:mock-b"}
    assert all(v == ["weekly-S-easy-TX-s1"] for v in manifest["not_rescored"].values())
    base = [r for r in new["rows"] if r["system"].startswith("baseline:")]
    for r in base:
        if r["scenario"] == "weekly-S-easy-TX-s1":
            assert r["outcome"] == "unavailable"
            continue
        assert r["reused_from"] and r["outcome"] == old[r["key"]]["outcome"]
        assert r.get("hard_count") == old[r["key"]].get("hard_count")  # same config -> same score
    html = (tmp_path / "reports" / "new" / "report.html").read_text()
    assert "re-scored" in html and "Not re-scored" in html
    # The old reply files are carried over verbatim.
    a = tmp_path / "runs" / "old" / "baseline_mock-a" / "weekly-M-easy-TX-s1" / "raw_output.txt"
    b = tmp_path / "runs" / "new" / "baseline_mock-a" / "weekly-M-easy-TX-s1" / "raw_output.txt"
    assert a.read_text() == b.read_text()
