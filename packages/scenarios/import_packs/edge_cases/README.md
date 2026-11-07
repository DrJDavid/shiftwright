# edge_cases: one importer edge per file

Import `roster_base.csv` first (E1, E2) into an empty TX store open 08:00–22:00, 30-min slots, then the
file under test. "Bug" rows are xfail tests in `../test_packs.py`.

| File | Kind | Edge | Result |
|---|---|---|---|
| roster_base.csv | roster | Age column instead of DOB | Imports E1, E2 |
| roster_bom.csv | roster | UTF-8 BOM before `Employee ID` | Handled: header reads `Employee ID` |
| roster_first_last_age.csv | roster | `First Name` + `Last Name`, `TM ID`, `Hourly Rate`, `Cell` `+1 512 555 0193` | Name joined, phone E.164, all mapped |
| roster_missing_wage.csv | roster | No wage column | Preview: "Still needed: wage per hour"; commit refused (422) |
| roster_header_only.csv | roster | Header, no rows | Preview warning "The file has no data rows."; commit 400 |
| roster_utf8_names.csv | roster | `José Núñez-Ortíz` | Kept exactly |
| training_list_in_cell.csv | training | `Cashier\|Drive Up/Guest Service Desk`, `Cashier, Drive Up` | Split on `\| / , ;` |
| availability_overnight.csv | availability | `22:00-06:00`, `6pm-12am` | Unavailable until 22:00 / 18:00 that day. The next morning (00:00–06:00) is **not** marked available on the following day (limitation) |
| forecast_overnight_window.csv | forecast | `22:00-06:00` in one column | Fri 1320–1800 (correct) |
| forecast_overnight_end_column.csv | forecast | Start `10:00 PM`, End `6:00 AM` in separate columns | **Bug:** saved as start 1320, end 360 (end < start); the solver then reports 100% coverage with 0 shifts |
| forecast_15min_slots.csv | forecast | 15-min interval rows | 15-min store: merged correctly. **Bug** in a 30-min store: each row becomes a 30-min block → overlapping, off-grid requirements (600–630 hc 2 overlaps 615–645 hc 3 …), no warning |
| forecast_hourly_start_only.csv | forecast | Hourly rows, start only | **Bug:** 10:00–10:30, 11:00–11:30, 12:00–12:30 instead of 10:00–13:00 |
| forecast_other_week_dates.csv | forecast | Date 2026-11-18 (next week) | **Bug:** silently lands on Wednesday of this week |
| forecast_fractional_hc.csv | forecast | Headcount `0.5`, `1.6` | **Bug:** 0.5 dropped, 1.6 → 1, no warning |
| history_basic.csv | history | `Shift Date`/`Shift Start`/`Shift End`, `11/02/2026` and `02-Nov-2026`, 12h and 24h | Stored correctly |

## Not supported (no test files on purpose)
The importer reads comma-separated UTF-8 text with the header on line 1 and nothing else:
- semicolon- or tab-delimited files (a whole line becomes one column)
- `.xlsx` / `.xls` (the file picker only accepts `.csv`)
- Windows-1252 / Latin-1 encodings: non-ASCII letters become `�` silently
- header not on the first line (report titles, multi-row headers): see messy_mid_ca history.csv
- long-format availability (one row per employee per day) and wide forecasts (one column per time interval)
- `Noon` / `Midnight` words, `Last, First` name flipping, dates like `March 3, 1999` or `2026/11/09`
