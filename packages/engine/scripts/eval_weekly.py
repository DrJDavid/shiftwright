"""Run solve_week on WS5's weekly eval scenarios and validate.

    uv run python packages/engine/scripts/eval_weekly.py [S|M|L ...]
"""
from __future__ import annotations

import sys
import time

from shiftwright_engine import solve_week
from shiftwright_laws import resolve
from shiftwright_scenarios import generate
from shiftwright_validator import validate

sizes = sys.argv[1:] or ["S", "M"]
for size in sizes:
    for diff in ["easy", "tight", "legal_trap"]:
        jur = "CA" if diff == "legal_trap" else "TX"
        sc = generate(1, size, diff, jur)
        cfg = sc.config
        cfg.law_pack = resolve(cfg.store.jurisdiction)
        t = time.perf_counter()
        s = solve_week(cfg, time_limit_s=30)
        wall = time.perf_counter() - t
        hard = [v for v in validate(cfg, s).violations if v.severity == "hard"] if s.shifts else []
        st = s.solver_stats or {}
        obj = s.metrics.objective_dollars if s.metrics else None
        print(f"{size} {diff} {jur}: status={s.status} wall={wall:.1f}s obj={obj} shifts={len(s.shifts)} "
              f"cands={st.get('num_candidate_shifts')} cov={s.metrics.coverage_pct if s.metrics else None} "
              f"hard={len(hard)} {[v.code.value for v in hard[:5]]} solver={st.get('solver_status')} "
              f"err={st.get('error')}", flush=True)
