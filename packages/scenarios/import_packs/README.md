# CSV import packs

CSV files to import through the real UI (chat → CSV import card) and an automated check that runs the
same flow against the real API. All people are synthetic; every phone is 555-01xx.

| Pack | What it tests |
|---|---|
| [clean_small_tx/](clean_small_tx/README.md) | 15 staff, tidy headers, everything auto-maps: the happy path end to end |
| [corporate_mid_tx/](corporate_mid_tx/README.md) | 40 staff, Workday/Kronos-style headers, 7 departments, 30-min interval forecast, truck Tue/Thu/Sat 4 am |
| [messy_mid_ca/](messy_mid_ca/README.md) | 27 planted problems (junk columns, blank rows, mixed formats, duplicates, a 16-year-old on forklift, a sub-minimum wage, unknown codes, report header above the column header) |
| [edge_cases/](edge_cases/README.md) | 15 tiny files, one importer edge each, plus the formats that are *not* supported |
| [demand/](demand/README.md) | Corporate **demand** exports in five styles (per-slot headcount, staffing plan, department hours, sales + labor standards, truck cases) × four weeks (normal, Thanksgiving/Black Friday, promo, light January), all on corporate_mid_tx's roles, plus the conversion spec for WS6 |

Each pack folder has `roster.csv`, `training.csv`, `availability.csv`, `forecast.csv`, `history.csv`, a
README (what to do in the UI and what should happen) and `leader_setup.json`: what the leader has to
tell the chat because no CSV carries it (hours, slot size, week, pre-open, payroll cap, role priorities,
manual mappings, and for messy, the review fixes).

**Import order:** roster → training → availability → forecast → history (training and availability
look employees up by ID, so the roster must come first).

## Regenerate / verify

```
uv run python packages/scenarios/import_packs/build.py          # rewrite the CSVs (deterministic)
uv run pytest packages/scenarios/import_packs -rxX              # ~50 s: 3 real solves at 20 s limit
uv run python packages/scenarios/import_packs/packs_harness.py  # human-readable run per pack
```

`packs_harness.py` uses `create_app` + FastAPI `TestClient` (temp SQLite, no LLM key, so name-matching
mapping) and does what the UI does: create store (template `empty`) → PUT store basics → for each file
preview, then commit the proposed mapping (plus only the manual fixes the pack README documents),
sending just `rows_preview` like `CsvImportCard` → PUT payroll cap + priorities → readiness → solve
(`time_limit_s` 20). Tests marked xfail document the bugs below; they turn into XPASS when fixed.

## Results (run Fri Nov 6 2026, main @ 4f53a85, real engine + validator)

| Pack | Mapping | Import | Readiness | Solve (20 s) |
|---|---|---|---|---|
| clean_small_tx | all 5 files auto-map | 15 employees, 5 roles, 49 demand blocks, 116 history rows, 0 skipped rows | ready | feasible, 79 shifts, **99.9% coverage**, 391.5 h, validator **passed** |
| corporate_mid_tx | roster needs `Home Org` → home department; history needs `Punch In` → start; rest auto | 40 employees, 7 depts, 8 roles, 1,184 interval rows merged to 94 blocks, truck 04:00–10:00 ×3, 0 skipped | ready | feasible, 103 shifts, **94.4% coverage**, 788.5 h, validator **passed** |
| messy_mid_ca | `Manager` wrongly proposed as age (set to Ignore); history unmappable (title rows) | 24/25 employees, 10 roles; 8 roster, 13 training, 9 availability, 1 forecast warnings; history 422 | **red**: minimum_wage ($15.50 < $16.90, CA.minimum_wage.1) + "Nobody trained for: beauty" | after review fixes: ready; untagged FORKLIFT → engine put the **16-year-old on forklift, validator passed**; after tagging the role (PIT tag, min age 18) → adult on forklift, validator passed |
| edge_cases | as designed | see edge_cases/README.md | – | – |

Clean pack with no priorities step: readiness **ready**, solve returns 0 shifts / 0% coverage, validator passed.

## Importer bugs / limitations found (for WS6; none worked around in the packs)

Safety / correctness first:

1. **Imported PIT/forklift role isn't protected.** Roles created by an import get no `role_tags` and
   `min_age` 0, so `minor_prohibited_roles` (federal, `powered_industrial_truck`) never applies. With
   messy_mid_ca the engine scheduled the 16-year-old on FORKLIFT and the validator passed it. Suggest:
   flag role names matching forklift/PIT/reach/pallet jack/order picker lift for a confirm-the-tag card,
   and/or a readiness check "minors trained on untagged equipment roles". Also: there's no card to set
   role tags today. (A store on `bigbox_mid` with the CSV saying exactly "PIT Operator" is safe, because
   the name resolves to the template role.)
2. **Readiness is green with $0/h roles.** Every imported role gets gap penalty $0; if the leader skips
   priorities, `/solve` returns an empty week (0 shifts, 0% coverage) and the validator passes. Suggest a
   readiness check "roles with demand but $0 priority".
3. **Two-digit birth years go to the future.** `7/4/62` → 2062 → age −36, no warning (Python `%y`
   pivot). A 64-year-old becomes a "minor" for the engine. Suggest: if the parsed DOB is in the future,
   subtract 100 years; warn on ages outside 14–100.
4. **Per-slot forecast rows with only a start time are assumed to be one store slot long.** Hourly rows in
   a 30-min store lose half the demand; 15-min rows in a 30-min store create overlapping off-grid
   requirements (headcount double-counted). Suggest: infer the interval from the gap between
   consecutive starts, and reject or warn on off-grid times.
5. **Overnight forecast with a separate End column** (`10:00 PM`, `6:00 AM`) is saved with end < start;
   the solver then reports 100% coverage. The single-column window form (`22:00-06:00`) works. Fix: add
   1440 when end ≤ start, as `parse_window` does. (Also: DemandRequirement end ≤ start isn't rejected by
   config validation.)
6. **Commit-time warnings never reach the UI.** Skipped rows, unknown employees, "unknown role added",
   bad dates: all are saved to kv `import_warnings` but `/import/{kind}/commit` returns only the
   StoreConfig and there's no GET for them. The card shows only preview warnings (just the "name
   matching" note). Suggest returning `{config, warnings}` or adding `GET /import/{kind}/warnings`
   (contract change → API.md).
7. **`Manager` column → age.** The substring pass matches "age" inside "Manager" (also "Language",
   "Wage …", "Mileage"). Keeping the proposal skips every roster row. Suggest word-boundary matching.
8. **"Not Available" availability is read as available** (warning only). Add `not available`, `not avail`,
   `unavail`, `closed`, `-` to the OFF words.
9. **Fractional headcounts are truncated silently** (`0.5` → dropped, `1.5` → 1). Suggest rounding up
   or a warning.
10. **Duplicate employee rows: last one wins, no warning.**
11. **Bad phones accepted.** `555-0185` → `+5550185` (not valid E.164), no warning.
12. **Forecast dates outside the schedule week** land on the same weekday silently (`% 7`).
13. **`Seas` status → part_time** (only `season…`/`temp…` count as seasonal).
14. **Header must be line 1.** Kronos/Workday report titles above the header make the file unmappable
    (clear failure, but the leader must edit the file). Could skip leading lines until one maps.
15. Minor/limitations: `Punch In` isn't a history start synonym (while `Punch Out` maps to end via
    "out"); `Home Org` / `Org` aren't department synonyms; `Hire Dt` isn't a hire date synonym (hire date
    silently = week start); roles created from training take the department of the first employee
    trained on them (e.g. Cashier lands in Leadership); overnight availability doesn't carry into the
    next morning; encodings other than UTF-8 are replaced with `�` silently.

For WS7 (`CsvImportCard.tsx`): `missing = unmapped_required − mapped targets` compares against the
server's list literally. When the server reports `age` (no age/DOB mapped) and the leader maps
`birth_date`, or reports `name` and the leader maps first + last, or `avail_mon..avail_sun`, the
"Still needed" message never clears and Import stays disabled. Re-run preview logic client-side or
ask the server.
