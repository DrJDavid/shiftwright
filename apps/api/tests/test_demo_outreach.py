"""E2E: demo store -> solve -> fix (Saturday call-outs) -> scripted mock outreach -> filled. Needs the real fix_day."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from shiftwright_api import integrations

pytestmark = pytest.mark.skipif("engine.fix_day" in integrations.active_stubs(),
                                reason="engine.fix_day has not landed yet")


def test_demo_outreach_fills():
    path = Path(__file__).resolve().parents[1] / "scripts/demo_outreach.py"
    spec = importlib.util.spec_from_file_location("demo_outreach", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = mod.run(reply_delay_s=0.05)
    assert res["status"] == "filled", res
    assert res["first_text_s"] is not None and res["first_text_s"] < 2.0
