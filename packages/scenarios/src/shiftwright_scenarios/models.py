"""Scenario: one synthetic store plus everything evals need to score against it.

Not in contracts/models.py (contract gap, see STATUS.md); WS5 imports it from here.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from shiftwright_contracts.models import CallOut, Schedule, StoreConfig


class Scenario(BaseModel):
    config: StoreConfig
    history: list[Schedule] = Field(
        default_factory=list, description="Past weeks (oldest first), produced_by='history'."
    )
    narrative: str = Field("", description="How a store leader would describe the store.")
    callout_events: list[CallOut] = []
    expected: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Keys: seed, size, difficulty, infeasible (bool), conflicting_ids, "
            "narrative_facts, narrative_omissions, narrative_contradictions, traps, "
            "required_hours, budget_ratio, notes."
        ),
    )
