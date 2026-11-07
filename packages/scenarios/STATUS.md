# WS4 status

**Done:**
- `fixtures/tiny_store.json`: 6 employees, 4 roles (`leader_on_duty`, `cashier`, `truck_unload`,
  `pit_operator`), open Fri (day 4) and Sat (day 5) 08:00–20:00, 30-min slots, TX, week of
  2026-11-09. Saturday truck 06:00–10:00 (`pre_open_minutes` = 120). Validated by
  `tests/test_tiny_store.py`.

- **Contract gap:** `Scenario` isn't in `contracts/models.py`. Defined as a pydantic model in
  `shiftwright_scenarios.models` and exported from the package root
  (`from shiftwright_scenarios import Scenario`). Fields: `config`, `history`, `narrative`,
  `callout_events`, `expected`. WS5 imports it from here.
- Generator: `generate(seed, size="S"|"M"|"L", difficulty, jurisdiction="TX" | "WA/seattle" | Jurisdiction)`.
  Deterministic: identical output for the same arguments, across processes. Tests in `tests/test_generator.py`.
  - Sizes: S = 27 staff, 9 roles, trucks Wed+Sat. M = 60 staff, 14 roles, trucks Tue/Thu/Sat. L = 120 staff, 14 roles, 4 trucks.
    Store open 08:00–22:00 daily (98 h), trucks 04:00–10:00.
  - Difficulties: `easy` (cap = 1.2 × need), `normal` (need ≈ 105% of cap), `tight` (cap = 0.9 × need),
    `legal_trap` (2 minors PIT-trained + 3 clopen-prone employees, ids in `expected.traps`; pass
    `jurisdiction="CA"` for meal-break traps), `infeasible` (one of two seeded variants: a single
    LOD-trained leader, or every leader unavailable for the same 2 open hours; `expected.infeasible`,
    `expected.conflicting_ids` in `Infeasibility.conflicting_*` style, `expected.infeasible_summary`),
    `messy` (narrative omits 2 facts and contradicts 1: `expected.narrative_omissions`,
    `expected.narrative_contradictions`). `normal` is an extra level beyond the brief's list.
  - `expected.narrative_facts`: the facts the narrative states, as dicts keyed by `kind`.
  - `history`: 8 past weeks built by a greedy pass, with `produced_by="history"`, no breaks, and
    `metrics=None` (we don't claim numbers nobody checked).
  - `callout_events`: 3 call-outs at 06:04 on the last truck day, picked before any schedule exists, so
    they may name someone the engine didn't schedule. **Evals should use
    `pick_callouts(config, schedule, day, n, now, seed)`**, which picks from real shifts (leaders excluded by default).

**In progress:**
- demo store, CSV exports.

**Blocked on:** nothing.

**Shortcuts taken / notes for other workstreams:**
- The brief's "easy reaches ≥98% coverage with the engine" test exists but skips until
  `shiftwright_engine.solve_week` lands. It accepts coverage_pct as 0–1 or 0–100, since the contract
  doesn't fix the unit.
- Demand requirements for the same (role, day) never overlap in our fixtures, so headcount is
  read per slot, not summed. A test enforces this.
- `leader_on_duty` gap penalty (100 $/h) isn't in the brief's penalty list; chosen as the highest
  priority. It's also `always_staffed` (hard), so the penalty rarely matters.
- No law is baked into fixtures (`law_pack` is null; no `source: law` constraints). The PIT trap
  relies on `Role.min_age = 18` + `role_tags` and the law pack from `data/laws`.

## tiny_store hand check

Required: 63 headcount-hours (leader 24, cashier 32, truck 4, PIT 3). Cap 70 h.
A full-coverage schedule (66 h, 0 soft penalty) exists:

| Emp | Fri | Sat |
|---|---|---|
| e1 Alex (leader) | 08–14 leader | 08–14 leader |
| e2 Blair (leader) | 14–20 leader | 14–20 leader |
| e3 Casey | 08–14 cashier | 14–20 cashier |
| e4 Jordan (17, PIT-trained) | 16–20 cashier | 08–14 cashier |
| e5 Morgan | off | 06–09 PIT, 09–10 truck |
| e6 Riley | 11–19 cashier | 06–10 truck, 10–14 cashier |

Traps to check: Jordan (e4, age 17) is trained on `pit_operator` but must never be scheduled on it.
Jordan is unavailable Fri before 15:00. Casey/Jordan `not_together` (soft, $25/overlapping hour).
Only Morgan can legally run PIT, so Morgan calling out on Saturday leaves a PIT gap no one can fill.
