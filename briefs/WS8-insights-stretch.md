# WS8 (stretch) — Pattern mining from past schedules

**Folder:** `packages/insights/` (`shiftwright_insights`) · **Oversight:** partner · **Start only after M2.**

## Goal
`mine_patterns(config, history: list[Schedule]) -> list[Constraint]`. Every returned constraint
has `source=inferred`, `status=provisional`, and `evidence` text with counts.

Deterministic statistics only (no LLM):
- Minimum headcount per role per time block that held in ≥ 7 of 8 weeks and exceeds the current demand → propose a leader demand override, described in a constraint note (or a `DemandRequirement` suggestion).
- Employee never scheduled in a window across all weeks while not marked unavailable → propose a `preferred_off` availability entry.
- Two employees never overlapping despite both working the same day often → propose `not_together` (soft).
- Employees who never get opens/closes vs others who always do → suggest a `fair_spread`.
- Typical max shift length or days per week if stricter than the law → propose the matching kind.

Rank by confidence, return at most 8, so the onboarding doesn't drown the user in cards.

## Acceptance
On the demo store history, finds the "≥2 cashiers after 5pm" pattern and the Jordan/Casey separation.
