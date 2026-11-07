"""What each rule kind needs (contracts: ConstraintKind docstring), checked before a rule is saved and before a solve.

A rule saved without its parameters (e.g. min_shift_length with no `minutes`) used to crash the engine and lose
the whole week. The agent now gets a precise error at save time, and anything that slipped in some other way is
set aside at solve time with a note instead of failing the build.
"""
from __future__ import annotations

from typing import Optional

from shiftwright_contracts.models import StoreConfig

# kind -> (required params, an example the agent can copy)
RULE_PARAMS: dict[str, tuple[tuple[str, ...], dict]] = {
    "min_shift_length": (("minutes",), {"minutes": 240}),
    "max_shift_length": (("minutes",), {"minutes": 480}),
    "min_rest_between_shifts": (("minutes",), {"minutes": 600}),
    "max_days_per_week": (("days",), {"days": 5}),
    "max_consecutive_days": (("days",), {"days": 5}),
    "min_hours_week": ((), {}),
    "not_together": (("employee_ids",), {"employee_ids": ["<id or name>", "<id or name>"]}),
    "fair_spread": (("shift_class", "max_per_employee"), {"shift_class": "close", "max_per_employee": 3}),
    "always_staffed": (("role_id", "windows"), {"role_id": "<role id>", "windows": "store_hours"}),
    "preferred_role": (("employee_id", "role_id"), {"employee_id": "<id or name>", "role_id": "<role id>"}),
    "week_stability": ((), {}),
}


def problem(kind: str, params: Optional[dict]) -> Optional[str]:
    """A one-line reason the rule can't be used, or None if it's complete."""
    need, example = RULE_PARAMS.get(kind, ((), {}))
    p = params or {}
    missing = [k for k in need if p.get(k) in (None, "", [])]
    if missing:
        return f"{kind} needs params {', '.join(missing)} (e.g. {example})"
    if kind == "not_together" and len(p.get("employee_ids") or []) != 2:
        return "not_together needs exactly two employee_ids"
    return None


def usable(config: StoreConfig) -> tuple[StoreConfig, list[str]]:
    """The config with incomplete rules set aside, plus a note per rule dropped."""
    keep, notes = [], []
    for c in config.constraints:
        why = problem(c.kind.value, c.params)
        if why and c.status.value == "confirmed":
            notes.append(f"Rule {c.id} was set aside: {why}. Fix it on the rulebook to apply it.")
        else:
            keep.append(c)
    if not notes:
        return config, []
    return config.model_copy(update={"constraints": keep}), notes
