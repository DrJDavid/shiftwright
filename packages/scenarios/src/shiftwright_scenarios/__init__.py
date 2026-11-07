"""Seeded synthetic stores and demo fixtures (WS4).

Public API:
    Scenario                  pydantic model (config, history, narrative, callout_events, expected)
    generate(seed, size, difficulty, jurisdiction) -> Scenario
    DIFFICULTIES              ["easy", "normal", "tight", "legal_trap", "infeasible", "messy"]
    pick_callouts(config, schedule, day, n, now, seed) -> list[CallOut]
    load_tiny_store(), load_demo_store(locality="austin"), load_demo_scenario(locality="austin")
    DEMO_LOCALITIES           ("austin", "chicago", "seattle", "sf")
    DEMO_STORES               DEMO_LOCALITIES + ("restaurant",)
    generate(..., sector="food")  restaurant scenarios (food.py)
    make_dataset(sector, size, difficulty, state, city, seed) -> dict[str, bytes]   test-company files (dataset.py)
    make_dataset_zip(...) -> bytes, dataset_meta(...) -> dict
"""
from .callouts import pick_callouts
from .fixtures import DEMO_LOCALITIES, DEMO_STORES, FIXTURES_DIR, load_demo_scenario, load_demo_store, load_tiny_store
from .dataset import dataset_meta, make_dataset, make_dataset_zip
from .generator import DIFFICULTIES, generate
from .models import Scenario

__all__ = [
    "DEMO_LOCALITIES",
    "DEMO_STORES",
    "DIFFICULTIES",
    "FIXTURES_DIR",
    "Scenario",
    "dataset_meta",
    "generate",
    "load_demo_scenario",
    "load_demo_store",
    "load_tiny_store",
    "make_dataset",
    "make_dataset_zip",
    "pick_callouts",
]
