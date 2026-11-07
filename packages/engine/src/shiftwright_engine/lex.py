"""Coverage-first objective (SEMANTICS #25): tiers and their weights.

Roles are ranked into tiers by `gap_penalty_per_hour` (equal values share a tier; a penalty ≤ 0
means the role's demand carries no priority). The solve is two-staged (`model.solve`): first the
tier-weighted uncovered minutes are minimized with no money in the objective, then every tier's
uncovered minutes are locked at that result and cost is minimized. Within the coverage stage, a
tier's weight per uncovered minute is
  - strictly lexicographic (more than all lower tiers' demand minutes combined) when that fits in
    int64 for CP-SAT, else
  - R× the tier below, with R as large as fits (logged in solver_stats as `tier_ratio`).
Hard always_staffed that a model prices instead of enforcing (day LNS, fix_day) is a tier above
every role. Below the lowest tier, the coverage stage counts paid minutes at weight 1 (hours, not
money: idle paid time would use up a binding hours budget); the lowest tier weighs more per minute
than the longest candidate shift, so a shift that covers any more demand is always worth its hours.
"""
from __future__ import annotations

from shiftwright_contracts.models import ConstraintKind, Strength

from .prep import Prep

ALWAYS_TIER = float("inf")
LIMIT = 1 << 62  # Σ weight × max uncovered minutes stays inside int64
import os
MAX_RATIO = int(os.environ.get('ENGINE_TIER_RATIO_MAX', 1 << 20))


def role_tier(p: Prep) -> dict[str, float]:
    """role id -> tier key (its gap_penalty_per_hour), only for roles with a positive penalty."""
    return {r.id: r.gap_penalty_per_hour for r in p.cfg.roles if r.gap_penalty_per_hour > 0}


def tier_minutes(p: Prep, with_always: bool) -> dict[float, int]:
    """Upper bound on uncovered headcount-minutes per tier."""
    tier = role_tier(p)
    out: dict[float, int] = {}
    for (r, _a), dem in p.demand.items():
        if r in tier:
            out[tier[r]] = out.get(tier[r], 0) + dem * p.slot
    if with_always:
        n = 0
        for c in p.constraints:
            if c.kind == ConstraintKind.always_staffed and c.strength == Strength.hard:
                which = c.params.get("windows", "store_hours")
                for lo, hi in (p.store_open if which == "store_hours" else p.windows).values():
                    n += hi - (lo - lo % p.slot)
        if n:
            out[ALWAYS_TIER] = n
    return out


def weights(minutes: dict[float, int], base: int = 1, floor: int = 0) -> tuple[dict[float, int], int]:
    """(tier key -> weight per uncovered minute, ratio between adjacent tiers; 0 = strict).
    The lowest tier weighs `base` per minute; `floor` = objective units used below it (paid minutes)."""
    keys = sorted(minutes)
    w: dict[float, int] = {}
    acc = floor
    for i, k in enumerate(keys):
        w[k] = max(base, acc + 1) if i == 0 else acc + 1
        acc += w[k] * minutes[k]
    if acc <= LIMIT or not keys:
        return w, 0
    total = max(1, sum(minutes.values()))
    n = max(1, len(keys) - 1)
    room = max(1.0, (LIMIT - floor) / (base * total))
    ratio = max(2, min(MAX_RATIO, int(room ** (1 / n))))
    while ratio > 2 and base * ratio ** n * total + floor > LIMIT:
        ratio -= 1
    return {k: base * ratio ** i for i, k in enumerate(keys)}, ratio


def tier_weights(p: Prep, with_always: bool) -> tuple[dict[str, int], int, int]:
    """(role id -> weight per uncovered minute, always_staffed weight per minute or 0, ratio)."""
    w, ratio = weights(tier_minutes(p, with_always))
    tier = role_tier(p)
    return {r: w[k] for r, k in tier.items() if k in w}, w.get(ALWAYS_TIER, 0), ratio


__all__ = ["ALWAYS_TIER", "role_tier", "tier_minutes", "tier_weights", "weights"]
