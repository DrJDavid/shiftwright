"""Loaders for the committed fixtures."""
from __future__ import annotations

from pathlib import Path

from shiftwright_contracts.models import StoreConfig

from .models import Scenario

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def load_tiny_store() -> StoreConfig:
    return StoreConfig.model_validate_json((FIXTURES_DIR / "tiny_store.json").read_text())


def load_demo_store() -> StoreConfig:
    return StoreConfig.model_validate_json((FIXTURES_DIR / "demo_store.json").read_text())


def load_demo_scenario() -> Scenario:
    return Scenario.model_validate_json((FIXTURES_DIR / "demo_scenario.json").read_text())
