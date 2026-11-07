# C3 (revised 07:30): rules and coverage first, real dollars only for real money, tradeoffs go to the manager

*Supersedes the C3 text in `PUNCHLIST.md`. David's calls (Sat 07:00–07:30): dollars must never decide whether
a rule is kept or an hour is covered; when keeping one costs real money or budget, show the manager the
tradeoff and let them decide.*

## The order the engine optimizes (strict; each step only breaks ties of the one above)

1. **Firm rules and the law: never broken** (unchanged).
2. **Coverage by priority tier**: Must cover → Important → Nice to have (`Role.gap_penalty_per_hour` is read
   as a rank, not a price; equal values = same tier).
3. **Preferences** (soft rules), by importance: Strong preference → Preference (`Constraint.weight_dollars`
   read as a rank; equal values = same tier). Minimize how many are broken (or by how much, per kind's unit).
4. **Lowest real cost**: wages + overtime + legal premiums. The hours/dollar budget stays a hard cap.

No made-up dollars are traded against real ones. `objective_dollars` and the other reported metrics keep their
current formulas so the validator's recompute still matches; only the optimization order changes.

## Tradeoffs the manager decides (not the engine)

Steps 2–3 can cost real money or hit the budget cap. When they do, the engine reports it instead of deciding:
- After the main solve, for each **preference that was honored at a real cost** and each **gap left only because
  of the budget cap**, run a short what-if solve (the rule relaxed, or the cap +N hours) and record the real
  difference: dollars, hours, coverage.
- Return them on the schedule as structured `solver_stats.tradeoffs`: `[{id, kind: "preference_cost" |
  "budget_gap", rule_id?, role_id?, day, window?, if_kept: {wage_cost, hours, coverage_pct},
  if_dropped: {...}}]`, top 5 by size, each from an actual solve (never estimated).
- The agent turns each into an `ask_tradeoff` card in plain words, with only real numbers:
  "Keeping Sam on mornings costs $120 more this week. Keep it?" · "Covering Tue 2–4 pm needs 3 hours over your
  budget ($51). Approve the hours, or leave it open?" The answer updates the rule (keep / drop) or creates a
  budget approval (`approve_budget_increase`, already gated on the tradeoff card).
- Time budget: what-ifs only after the main solve, ≤ 5 of them, ≤ 5 s each; skipped (with a note) if the main
  solve used its whole time limit.

## UI (Lane B)

- No dollars on rules or priorities anywhere. The rule card offers **Firm rule · Strong preference ·
  Preference · Not a rule** (today it shows a "$ weight" field; replace it). Priorities: Must cover ·
  Important · Nice to have (already done on the roles card).
- Schedule header shows "Preferences not met: N" (from `soft_violations`), not a soft-penalty dollar total.
- Tradeoffs appear as the agent's cards in chat; the Schedule tab shows a small "2 decisions waiting" link.

## API (Lane A, after the engine)

- `priorities.py`: levels map to fixed tier values (`must_cover` 300, `important` 200, `nice_to_have` 100);
  drop the "priority below pay" readiness sub-check.
- Rule strength words → `weight_dollars` tiers: Strong preference 50, Preference 25 (rank only).
- Prompt: present `solver_stats.tradeoffs` as `ask_tradeoff` cards after a build, biggest first.

## Done when

All demo stores + Harbor Grill: 0 hard violations, coverage ≥ today's, ≤ 30 s main solve; validator
`audit_engine.py` agrees; at least one demo store produces a real `budget_gap` tradeoff and the agent shows it
as a card with the solve's numbers; engine/validator/API suites green; free rescore (`real-quick-*`,
`realistic-*` with cached replies) recorded in `packages/evals/STATUS.md`.
**Deadline 10:00.** If not green, it stays on its branch and the demo uses current behavior (plain-word
priorities with wage-based pricing), which already never asks managers for dollars.
