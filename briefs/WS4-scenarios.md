# WS4 — Scenarios, demo store, synthetic data

**Folder:** `packages/scenarios/` (`shiftwright_scenarios`) · **Oversight:** David
**Read first:** `SPEC.md`, `contracts/models.py`

## Goal
Realistic, seeded synthetic stores that everything else develops and evaluates against.

## Deliverables, in order
1. **`fixtures/tiny_store.json` within the first hour.** 6 employees, 4 roles, 2 open days
   (rest of the week closed), 30-min slots, TX. Hand-checkable. Everyone is blocked on this.
2. **Generator:** `generate(seed, size: "S"|"M"|"L", difficulty, jurisdiction) -> Scenario` where
   `Scenario = {config: StoreConfig, history: list[Schedule] (8 past weeks), narrative: str,
   callout_events: list[CallOut], expected: dict}`. Deterministic per seed.
3. **`fixtures/demo_store.json`**: "Store #0417, Austin TX", ~60 staff, built by the generator with a
   fixed seed and then hand-tuned for the demo script (SPEC §7): Jordan/Casey `not_together`; a
   17-year-old flagged PIT-trained; truck Saturday 04:00–10:00; a cashier pattern after 5pm in
   history; Saturday call-out scenario where repair is possible but not trivial; 2 demo phones
   (env `DEMO_PHONE_1/2`) on the first two outreach candidates.
4. **CSV exports** of the demo store in "corporate system export" style (`exports/roster.csv`,
   `training.csv`, `availability.csv`, `forecast.csv`, `history.csv`), with column names that
   *don't* match our field names (e.g. `TM_ID`, `Dept`, `Wage Rate`, `Avail Mon`), so the import
   mapping step has real work to do.

## Realism (from David's experience at a big-box store)
- Departments and roles:
  - Front of Store: `guest_service_desk`, `cashier`, `cart_attendant`, `drive_up`
  - General Merchandise: `softlines`, `hardlines`, `fitting_room`
  - Grocery: `grocery_stock`
  - Fulfillment: `order_picker`
  - Asset Protection: `ap_specialist`
  - Receiving: `truck_unload`, `backroom`, `pit_operator` (tag `powered_industrial_truck`, min_age 18)
  - Leadership: `leader_on_duty` (`always_staffed` during store hours)
- People are hired into a home department and trained in 1–3 of its roles; ~25% cross-trained
  into one role elsewhere. Leaders trained in `leader_on_duty`.
- Mix: ~30% full-time, 60% part-time, 10% seasonal; ~8% minors (16–17); wages $15–$22, leaders $24–$30.
- Corporate forecast drives demand: cashier/drive-up demand follows sales curves (peaks
  11–14 and 16–19, heavier weekends). `order_picker` follows online volume (morning-heavy).
  Truck days add `truck_unload` + `backroom` + `pit_operator` demand from 04:00 (pre-open).
- Hours budget set so that full coverage needs ~105% of the cap (normal difficulty), producing real trade-offs.
- Penalties: guest_service_desk 80, cashier 60, drive_up 50, truck_unload 70, pit_operator 70, order_picker 45, ap_specialist 40, grocery_stock 30, backroom 30, hardlines/softlines 25, cart_attendant 25, fitting_room 15.
- Availability: students unavailable weekdays before 15:00; some "no Sundays before noon";
  a few preferred_off entries with weights.
- `AttendanceStats` varied and plausible.

## Difficulty levels (for evals)
`easy` (budget ample) · `tight` (budget ~90% of need) · `legal_trap` (minors with PIT
training, CA store requiring meal breaks, clopen-prone availability) · `infeasible` (hard rules
truly conflict, e.g. `always_staffed` leader but only one leader trained and store open 98 h/week;
`expected.infeasible = true` + the conflicting ids) · `messy` (for intake evals: a narrative
with omissions and one contradiction).

## Narrative
`narrative` is how a store leader would describe the store to a new scheduler: rambling,
partial, using nicknames for departments. Template + seeded variation; no LLM needed. Store in
`expected.narrative_facts` the list of constraints the narrative implies, for intake recall scoring.

## Acceptance tests
- Same seed → byte-identical output. All outputs validate against `StoreConfig`.
- Every role in demand has ≥1 trained employee (except where an `infeasible` scenario requires otherwise).
- `easy` scenarios: engine (once available) reaches ≥98% coverage.
