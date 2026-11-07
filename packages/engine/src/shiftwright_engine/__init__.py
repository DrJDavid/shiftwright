"""CP-SAT schedule solve, fix, explain (WS1).

Public interface (the only functions other workstreams may call):
    solve_week, fix_day, explain_gap, find_conflicts
"""
from .explain import explain_gap
from .solve import find_conflicts, solve_week

__all__ = ["solve_week", "fix_day", "explain_gap", "find_conflicts"]


def fix_day(req, time_limit_s: float = 8):  # replaced in fix.py once implemented
    from .fix import fix_day as _fix_day

    return _fix_day(req, time_limit_s)
