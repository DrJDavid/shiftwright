"""Coverage per priority tier (SEMANTICS #25) for the demo stores, validated.

    uv run python packages/engine/scripts/tiers.py [--limit 30] [--only demo,chicago,...] [--json out.json]

One line per store: status, wall time (main solve and tradeoff what-ifs), tradeoffs, coverage, wage cost, hard violations, metrics_mismatch,
`cheaper_to_leave_gap` reasons, and missing headcount-hours per tier (highest tier first).
"""
from __future__ import annotations

import argparse
import json
import os
import time

from shiftwright_scenarios import load_demo_store
from shiftwright_validator import validate

from shiftwright_engine import solve_week
from shiftwright_engine.prep import build_prep

STORES = {"demo": None, "chicago": "chicago", "seattle": "seattle", "sf": "sf", "restaurant": "restaurant"}


def run(name: str, limit: float) -> dict:
    from engine_fixtures import with_law  # noqa: PLC0415

    cfg = with_law(load_demo_store(STORES[name]) if STORES[name] else load_demo_store())
    t = time.perf_counter()
    sched = solve_week(cfg, time_limit_s=limit)
    wall = time.perf_counter() - t
    rep = validate(cfg, sched)
    hard = [v for v in rep.violations if v.severity == "hard"]
    mm = [v.message for v in rep.violations if v.code.value == "metrics_mismatch"]
    pen = {r.id: r.gap_penalty_per_hour for r in cfg.roles}
    p = build_prep(cfg, with_cands=False)
    need: dict[float, float] = {}
    for (r, _a), dem in p.demand.items():
        need[pen.get(r, 0.0)] = need.get(pen.get(r, 0.0), 0.0) + dem * p.slot / 60
    miss: dict[float, float] = {}
    for g in sched.gaps:
        k = pen.get(g.role_id, 0.0)
        miss[k] = miss.get(k, 0.0) + g.missing_headcount * (g.end - g.start) / 60
    cheaper = sum(1 for g in sched.gaps for r in g.reasons if r.code.value == "cheaper_to_leave_gap")
    m = sched.metrics
    out = {
        "store": name, "status": sched.status, "wall_s": round(wall, 1),
        "main_s": sched.solver_stats.get("total_s"), "tradeoffs_s": sched.solver_stats.get("tradeoffs_s"),
        "tradeoffs": [(t["kind"], t.get("role_id") or t.get("rule_id"), t.get("day"), t.get("extra_hours"),
                       round(t["if_dropped"]["wage_cost"] - t["if_kept"]["wage_cost"], 2),
                       round(t["if_dropped"]["coverage_pct"] - t["if_kept"]["coverage_pct"], 2))
                      for t in sched.solver_stats.get("tradeoffs", [])],
        "soft_violations": len(sched.soft_violations),
        "coverage_pct": m.coverage_pct if m else None,
        "wage_cost": m.total_wage_cost if m else None,
        "objective": m.objective_dollars if m else None,
        "hours": m.total_hours if m else None, "budget_hours": m.budget_hours_cap if m else None,
        "hard": len(hard), "hard_codes": sorted({v.code.value for v in hard}), "metrics_mismatch": mm,
        "cheaper_reasons": cheaper,
        "tiers_missing_h": {str(k): round(miss.get(k, 0.0), 2) for k in sorted(need, reverse=True)},
        "tiers_need_h": {str(k): round(v, 2) for k, v in sorted(need.items(), reverse=True)},
        "load": os.getloadavg()[0],
    }
    return out


def main() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=float, default=30)
    ap.add_argument("--only", default=",".join(STORES))
    ap.add_argument("--json")
    a = ap.parse_args()
    res = []
    for name in a.only.split(","):
        r = run(name, a.limit)
        res.append(r)
        print(json.dumps(r), flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
