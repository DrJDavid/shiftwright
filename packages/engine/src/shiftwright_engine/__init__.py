"""CP-SAT schedule solve, fix, explain (WS1).

Public interface (the only functions other workstreams may call):
    solve_week, explain_gap, find_conflicts   (fix_day: not yet implemented, not exported)
"""
from .explain import explain_gap
from .solve import find_conflicts, solve_week

__all__ = ["solve_week", "explain_gap", "find_conflicts"]
