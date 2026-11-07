# CSV-packs status

_Last updated: Fri Nov 6 2026 ~01:00 CT, branch ws/csv-packs_

**Done:** four packs (clean_small_tx, corporate_mid_tx, messy_mid_ca, edge_cases), generator
`build.py` (deterministic, test checks committed files are up to date), `packs_harness.py`
(create_app + TestClient flow), `test_packs.py` (passes + xfails documenting importer bugs).
Results table and WS6 bug list in README.md.

**Notes:** the folder lives inside packages/scenarios (owned by WS4) but touches nothing else there.
Tests are collected by the root `uv run pytest` (testpaths includes `packages`) and add ~50 s
(three 20 s solves). If that's too slow for the root suite, the coordinator could exclude
`packages/scenarios/import_packs` or lower the time limit.

**Next (if wanted):** re-run after WS6 fixes; XPASS rows mean a bug is fixed → update README.
