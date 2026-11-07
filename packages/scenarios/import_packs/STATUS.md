# CSV-packs status

_Last updated: Sat Nov 7 2026, branch ws/csv-packs_

**Done:**
- Slice 1 (merged): four people/roster packs (clean_small_tx, corporate_mid_tx, messy_mid_ca,
  edge_cases), `build.py`, `packs_harness.py`, `test_packs.py`; WS6 bug list in README.md.
- Slice 2: `demand/`: five corporate demand styles × week variants, all derived from one synthetic
  truth per week (`demand/build_demand.py`) with reference math (`demand/spec_reference.py`).
  `demand/test_demand.py` records today's behaviour (per-slot + per-day plan work and solve;
  day ranges, dept hours, sales, trucks don't) and xfail tests pinning Specs 0–5 in `demand/README.md`.
  `packs_harness.store_basics` now accepts `week_start` and `hours_by_day`.

**Notes:** tests are collected by the root `uv run pytest`; slice 1 adds ~50 s and slice 2 ~60 s
(three 20 s solves each). The new import kinds in the spec (`labor_model`, `labor_hours`,
`labor_standards`, `sales_forecast`, `workload`) need a contracts/API.md change; names are constants
at the top of `demand/test_demand.py`.

**Next (if wanted):** when WS6 implements a spec, xfail → XPASS; then drop the marker and update the
README tables.
