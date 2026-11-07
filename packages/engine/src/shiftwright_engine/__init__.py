"""CP-SAT schedule solve, fix, explain (WS1).

Public interface (the only functions other workstreams may call):
    solve_week, fix_day, explain_gap, find_conflicts
"""
from .explain import explain_gap
from .fix import fix_day
from .solve import find_conflicts, solve_week

__all__ = ["solve_week", "fix_day", "explain_gap", "find_conflicts"]
