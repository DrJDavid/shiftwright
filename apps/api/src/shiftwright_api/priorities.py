"""Role priorities in plain words, as solver tiers.

Managers pick a level per role (Must cover · Important · Nice to have). The engine ranks roles by
`Role.gap_penalty_per_hour` (SEMANTICS #25: a rank, not a price; equal values share a tier), so each level
maps to one fixed tier value. A higher tier is always covered before a lower one; pay doesn't enter into it.

Levels live in the API's kv store (kind `role_priority`), not in the contract. Roles without a level
(hand-tuned demo stores) keep whatever value they already have.
"""
from __future__ import annotations

from typing import Any, Optional

LEVELS: dict[str, tuple[str, float]] = {
    "must_cover": ("Must cover", 300.0),
    "important": ("Important", 200.0),
    "nice_to_have": ("Nice to have", 100.0),
}
DEFAULT_LEVEL = "important"
_KV = ("role_priority", "levels")


def load(db: Any, store_id: str) -> dict[str, str]:
    return dict(db.get(store_id, *_KV, default={}) or {})


def save(db: Any, store_id: str, levels: dict[str, str]) -> None:
    db.put(store_id, *_KV, {k: v for k, v in levels.items() if v in LEVELS})


def label(level: Optional[str]) -> Optional[str]:
    return LEVELS[level][0] if level in LEVELS else None


def penalty(level: str) -> float:
    """The tier value (`gap_penalty_per_hour`) for a level."""
    return LEVELS[level][1]


def apply(d: dict, levels: dict[str, str]) -> None:
    """Set every leveled role to its tier value. Mutates the config dict."""
    for r in d.get("roles") or []:
        lvl = levels.get(r.get("id"))
        if lvl in LEVELS:
            r["gap_penalty_per_hour"] = penalty(lvl)
