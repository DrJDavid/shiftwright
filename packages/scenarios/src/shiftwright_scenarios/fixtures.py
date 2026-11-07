"""Loaders for the committed fixtures."""
from __future__ import annotations

from pathlib import Path

from shiftwright_contracts.models import StoreConfig

from .models import Scenario

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"


def load_tiny_store() -> StoreConfig:
    return StoreConfig.model_validate_json((FIXTURES_DIR / "tiny_store.json").read_text())


DEMO_LOCALITIES = ("austin", "chicago", "seattle", "sf")


def _demo_file(kind: str, locality: str) -> Path:
    if locality not in DEMO_LOCALITIES:
        raise ValueError(f"locality must be one of {DEMO_LOCALITIES}, got {locality!r}")
    return FIXTURES_DIR / (f"demo_{kind}.json" if locality == "austin" else f"demo_{kind}_{locality}.json")


def load_demo_store(locality: str = "austin") -> StoreConfig:
    """Store #0417 Austin TX by default; "chicago" | "seattle" | "sf" for the same store elsewhere."""
    return StoreConfig.model_validate_json(_demo_file("store", locality).read_text())


def load_demo_scenario(locality: str = "austin") -> Scenario:
    return Scenario.model_validate_json(_demo_file("scenario", locality).read_text())
