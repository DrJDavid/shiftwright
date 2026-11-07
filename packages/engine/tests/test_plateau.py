"""C4: solve_week(time_limit_s=None) stops when it stops improving, inside max_s."""
from __future__ import annotations

import time

from engine_fixtures import tiny_store, with_law
from shiftwright_engine import solve_week
from shiftwright_validator import validate


def test_small_store_plateau_mode_is_proven_close_and_fast():
    cfg = with_law(tiny_store())
    t = time.perf_counter()
    s = solve_week(cfg, time_limit_s=None)
    assert time.perf_counter() - t < 30
    st = s.solver_stats
    assert st["mode"] == "plateau" and st["stop_reason"] == "proven_close"
    assert st["main_s"] <= st["wall_s"] < 30
    assert not [v for v in validate(cfg, s).violations if v.severity == "hard"]


def test_explicit_limit_reports_time_limit():
    s = solve_week(with_law(tiny_store()), time_limit_s=5)
    assert s.solver_stats["stop_reason"] == "time_limit" and s.solver_stats["mode"] == "time_limit"
