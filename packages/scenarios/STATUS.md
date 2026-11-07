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
- **Contracts v1.1 (done):**
  - `Store.school_week`: `generate(..., school_week=True)` by default (Nov 9–15 2026 is a normal
    school week in Austin); `None`/`False` accepted. Not part of the seed key, so only the flag and
    `expected.school_week` change. `tiny_store.json`, demo store and demo scenario: `true`.
  - Wages: the generator now depends on `shiftwright-laws` and resolves the law pack on
    `WEEK_START`. If the minimum wage is above the base draw floor ($15), every wage is shifted up by
    the same amount (ceil-to-quarter(min) − 15); `expected.minimum_wage`, `expected.wage_lift`.
    TX output is unchanged (min $7.25). Tested for TX, TX/austin, CA, CA/san_francisco, WA/seattle,
    IL/chicago, NY/new_york × S/M/L × all difficulties × seeds 1–2: nobody below minimum except the trap.
  - `legal_trap` adds a `below_minimum_wage` trap: one adult full-timer with open availability (so
    they get scheduled), wage = floor(min − $1) to the quarter. `expected.traps.below_minimum_wage`
    = [id], `expected.traps.minimum_wage` = {dollars_per_hour, law_rule_id}.
- Generator: `generate(seed, size="S"|"M"|"L", difficulty, jurisdiction="TX" | "WA/seattle" | Jurisdiction, school_week=True)`.
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

- Demo store: `fixtures/demo_store.json` (StoreConfig) + `fixtures/demo_scenario.json` (full
  Scenario with history, narrative, call-outs, expected). Built by `shiftwright_scenarios.demo`
  (seed 417, M, normal) and hand-tuned. Regenerate with `uv run python -m shiftwright_scenarios.demo`;
  a test fails if the committed files drift from the builder. Loaders: `load_demo_store()`, `load_demo_scenario()`.
  - "Store #0417, Austin TX" (TX, city `austin`), 60 staff, 14 roles, trucks Tue/Thu/Sat 04:00–10:00.
  - Jordan (e007) / Casey (e019): `not_together` (soft $25), both evening-available cashiers; history never overlaps them.
  - e008, age 17, PIT-trained (the only minor with PIT).
  - Cashier habit: history has ≥2 cashiers every hour 17:00–22:00, all 8 weeks, while the weekday
    forecast asks for 1 after 19:00, so the mined rule adds information.
  - Saturday 06:04 call-outs: e034 (truck), e052 (PIT), e053 (cashier). Each has a Saturday
    04:00–14:00 `preferred_on` ($15/h) so the engine schedules them that morning.
  - Demo phones: e023 and e027 carry placeholder phones `+15125550198/99` and the best call-in record
    in the store (9/10, 8/9; nobody else ≥ 0.8). `apply_demo_phones(cfg)` swaps in `DEMO_PHONE_1/2`
    from the environment at runtime. Real numbers never go in the repo. To keep them free to call in
    Saturday: `preferred_off` Saturday at $60/h (wage + 60 > every gap penalty of their roles), and
    one-off approved time off Mon/Tue/Wed/Sun of the demo week (`on_date`, so history and the
    availability CSV are unaffected) so their hours stay under `max_hours_week`.
    Request filed: `contracts/requests/ws4-callin-preferred-off.md` (fix_day shouldn't charge
    preferred_off on a call-in).
- CSV exports: `fixtures/exports/{roster,training,availability,forecast,history}.csv`, corporate style
  (`TM_ID`, `Dept`, `Wage Rate`, `Avail Mon`, DOB instead of age, job codes, 12-hour times). The mapping
  tables and format notes are in the `shiftwright_scenarios.exports` docstring.

**In progress:** nothing. Open follow-up below.

**Engine verification (`shiftwright_scenarios.verify_demo`, `tests/test_demo_engine.py`):**
- `uv run python -m shiftwright_scenarios.verify_demo [time_limit_s]` solves the demo store (law pack
  resolved), checks the 3 call-outs have a Saturday shift running at 06:04 and starting before 12:00,
  that the demo phones aren't scheduled Saturday, and that they rank 1–2 for outreach: by the engine's
  `outreach_queue` if `fix_day` exists, else a proxy (callable = adult non-leader, trained in a
  called-out role, no Saturday shift, under max days/hours; sorted by (accepted+1)/(offered+2), then
  wage). On a miss it prints a `repick` from `pick_callouts()` (demo people excluded).
  The test skips while `shiftwright_engine.solve_week` is missing (it is on main right now).
- **Trial against `claude/ws-engine-97a072` (6cb51b9, scratch worktree, removed), Fri ~23:30:**
  - Before the nudges (120 s): e034, e052 on Saturday truck; e053 (seasonal) not scheduled; both
    demo phones scheduled Saturday → not callable. With `time_limit_s=30`: coverage 35.7%, so the
    engine hadn't converged (its STATUS: demo-scale perf in progress).
  - After the nudges, 120 s (~103 s wall), two runs: all 3 call-outs scheduled Saturday morning
    (e034 04:00–13:00 truck/backroom, e052 04:00–14:00 truck/softlines, e053 06:00/06:30– grocery/cashier);
    coverage 90–93%. Demo phones: one run e023 scheduled Saturday 11:00–19:00 ($40/h weight, since
    raised to $60), the other e027 scheduled Saturday 04:30–09:00 despite $60/h (a dominated choice,
    so the solve wasn't optimal). Proxy rank-1 was the free demo phone each time (0.82–0.83 vs ≤0.67).
  - 30 s run after the nudges: coverage 58.7%, none of the call-outs scheduled, both phones scheduled
    Saturday. Results depend on the engine reaching a near-optimal solve.
  - **Conclusion:** the fixtures are right once the weekly solve is near-optimal; re-run
    `verify_demo 120` when WS1's performance work lands. If the phones still land on Saturday, options:
    (a) raise `PHONE_PREFERRED_OFF` in `demo.py`, (b) the demo uses a pinned, checked schedule,
    (c) make Saturday 04:00–10:00 unavailable for them (then they can only be called for 10:00+).
- Brief test "easy → ≥98% coverage" (written, skips without the engine; not run in the trial).

**Blocked on:** nothing.

**Shortcuts taken / notes for other workstreams:**
- Demo store has 6 extra cashier cross-trains so the history habit holds through Sunday (the greedy
  history builder ran out of eligible cashiers by the end of the week otherwise).
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
