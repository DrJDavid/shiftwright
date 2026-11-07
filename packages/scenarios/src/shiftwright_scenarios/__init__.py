"""Seeded synthetic stores and demo fixtures (WS4).

Public API:
    Scenario                  pydantic model (config, history, narrative, callout_events, expected)
    generate(seed, size, difficulty, jurisdiction) -> Scenario
    DIFFICULTIES              ["easy", "normal", "tight", "legal_trap", "infeasible", "messy"]
    pick_callouts(config, schedule, day, n, now, seed) -> list[CallOut]
    load_tiny_store(), load_demo_store(locality="austin"), load_demo_scenario(locality="austin")
    DEMO_LOCALITIES           ("austin", "chicago", "seattle", "sf")
"""
from .callouts import pick_callouts
from .fixtures import DEMO_LOCALITIES, FIXTURES_DIR, load_demo_scenario, load_demo_store, load_tiny_store
from .generator import DIFFICULTIES, generate
from .models import Scenario

__all__ = [
    "DEMO_LOCALITIES",
    "DIFFICULTIES",
    "FIXTURES_DIR",
    "Scenario",
    "generate",
    "load_demo_scenario",
    "load_demo_store",
    "load_tiny_store",
    "pick_callouts",
]
