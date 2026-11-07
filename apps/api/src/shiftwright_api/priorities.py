"""Role priorities in plain words, priced for the solver.

Managers pick a level per role (Must cover · Important · Nice to have). The engine still needs a dollar
"gap penalty" per uncovered hour (contracts: `Role.gap_penalty_per_hour`), so each level maps to a multiple
of the highest wage among the people trained for that role. Every multiple is above 1, so with enough
budget and people every level gets covered; when hours or people run out, lower levels go uncovered first.

Levels live in the API's kv store (kind `role_priority`), not in the contract. Roles without a level
(hand-tuned demo stores, imported roles) keep whatever penalty they already have.
"""
from __future__ import annotations

import math
from typing import Any, Optional

LEVELS: dict[str, tuple[str, float]] = {
    "must_cover": ("Must cover", 3.0),
    "important": ("Important", 1.5),
    "nice_to_have": ("Nice to have", 1.1),
}
DEFAULT_LEVEL = "important"
FALLBACK_WAGE = 20.0  # before anyone is on the team
_KV = ("role_priority", "levels")


def load(db: Any, store_id: str) -> dict[str, str]:
    return dict(db.get(store_id, *_KV, default={}) or {})


def save(db: Any, store_id: str, levels: dict[str, str]) -> None:
    db.put(store_id, *_KV, {k: v for k, v in levels.items() if v in LEVELS})


def label(level: Optional[str]) -> Optional[str]:
    return LEVELS[level][0] if level in LEVELS else None


def base_wage(d: dict, role_id: str) -> float:
    """Highest wage among people trained for the role; else the store's highest wage; else a fallback."""
    emps = d.get("employees") or []
    trained = [float(e.get("wage_per_hour") or 0) for e in emps if role_id in (e.get("trained_role_ids") or [])]
    anyone = [float(e.get("wage_per_hour") or 0) for e in emps]
    return max(trained or anyone or [FALLBACK_WAGE]) or FALLBACK_WAGE


def penalty(level: str, wage: float) -> float:
    return float(math.ceil(LEVELS[level][1] * wage))


def apply(d: dict, levels: dict[str, str]) -> None:
    """Reprice every role that has a level, from current wages and training. Mutates the config dict."""
    for r in d.get("roles") or []:
        lvl = levels.get(r.get("id"))
        if lvl in LEVELS:
            r["gap_penalty_per_hour"] = penalty(lvl, base_wage(d, r["id"]))
