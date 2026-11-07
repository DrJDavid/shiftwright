"""Benchmark solve_week on the demo store and the synthetic demo-like store.

    uv run python packages/engine/scripts/bench.py [--single] [--limit 30] [--only demo|like|tiny]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from engine_fixtures import demo_like_store, tiny_store, with_law  # noqa: E402
from shiftwright_scenarios import load_demo_store  # noqa: E402
from shiftwright_validator import validate  # noqa: E402

import shiftwright_engine.solve as S  # noqa: E402


def run(name, cfg, limit):
    t = time.perf_counter()
    sched = S.solve_week(cfg, time_limit_s=limit)
    wall = time.perf_counter() - t
    rep = validate(cfg, sched)
    hard = [v for v in rep.violations if v.severity == "hard"]
    st = sched.solver_stats or {}
    m = sched.metrics
    print(f"{name}: status={sched.status} wall={wall:.1f}s obj=${st.get('phase1_objective_dollars')} "
          f"bound=${st.get('best_bound_dollars')} gap={st.get('relative_gap')} "
          f"coverage={m.coverage_pct if m else None} cands={st.get('num_candidate_shifts')} "
          f"hard_violations={len(hard)} {sorted({v.code.value for v in hard})} stages={st.get('stages')} "
          f"fallback={st.get('fallback')}")
    mm = [v for v in rep.violations if v.code.value == "metrics_mismatch"]
    if mm:
        print("   metrics_mismatch:", [v.message for v in mm])
    for v in hard[:5]:
        print("   ", v.code, v.message)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--single", action="store_true", help="force single-stage solve")
    ap.add_argument("--limit", type=float, default=30)
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    if a.single:
        S.SINGLE_STAGE_MAX_CANDS = 10**9
    cases = {"tiny": tiny_store, "demo": lambda: with_law(load_demo_store()), "like": demo_like_store,
             **{c: (lambda c=c: with_law(load_demo_store(c))) for c in ("chicago", "seattle", "sf", "restaurant")}}
    for name, mk in cases.items():
        if a.only and name not in a.only.split(","):
            continue
        run(name, mk(), a.limit)


if __name__ == "__main__":
    main()
