# WS4 status

**Done:**
- `fixtures/tiny_store.json`: 6 employees, 4 roles (`leader_on_duty`, `cashier`, `truck_unload`,
  `pit_operator`), open Fri (day 4) and Sat (day 5) 08:00–20:00, 30-min slots, TX, week of
  2026-11-09. Saturday truck 06:00–10:00 (`pre_open_minutes` = 120). Validated by
  `tests/test_tiny_store.py`.

**In progress:**
- `Scenario` model, generator, demo store, CSV exports.

**Blocked on:** nothing.

**Shortcuts taken / notes for other workstreams:**
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
