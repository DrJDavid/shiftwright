"""Smoke test: every workspace package imports and sees the same contracts."""
import importlib

import pytest

PACKAGES = [
    "shiftwright_contracts",
    "shiftwright_engine",
    "shiftwright_validator",
    "shiftwright_scenarios",
    "shiftwright_evals",
    "shiftwright_insights",
    "shiftwright_api",
    "shiftwright_laws",
]


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    importlib.import_module(name)


def test_contract_version():
    from shiftwright_contracts.models import CONTRACT_VERSION

    assert CONTRACT_VERSION == "1.2.0"
