"""Seeded synthetic stores and demo fixtures (WS4).

Public API:
    Scenario                  pydantic model (config, history, narrative, callout_events, expected)
    generate(seed, size, difficulty, jurisdiction) -> Scenario
    DIFFICULTIES              ["easy", "normal", "tight", "legal_trap", "infeasible", "messy"]
    pick_callouts(config, schedule, day, n, now, seed) -> list[CallOut]
    load_tiny_store(), load_demo_store(), load_demo_scenario()
"""
from .callouts import pick_callouts
from .fixtures import FIXTURES_DIR, load_demo_scenario, load_demo_store, load_tiny_store
from .generator import DIFFICULTIES, generate
from .models import Scenario

__all__ = [
    "DIFFICULTIES",
    "FIXTURES_DIR",
    "Scenario",
    "generate",
    "load_demo_scenario",
    "load_demo_store",
    "load_tiny_store",
    "pick_callouts",
]
