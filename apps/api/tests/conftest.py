"""Fixtures for WS6 tests. Helpers live in api_helpers.py (importable because of the path insert)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api_helpers import signup  # noqa: E402
from shiftwright_api.agent.llm import FakeLLM  # noqa: E402
from shiftwright_api.main import create_app  # noqa: E402
from shiftwright_api.settings import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(database_url=f"sqlite:///{tmp_path}/test.db", messenger="mock", agent_model="fake/model",
                    openrouter_api_key="", auth_required=True)


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM([])


@pytest.fixture
def app(settings, fake_llm):
    return create_app(settings=settings, llm=fake_llm)


@pytest.fixture
def client(app):
    """Signed in as one leader for the whole test."""
    with TestClient(app) as c:
        signup(c)
        yield c


