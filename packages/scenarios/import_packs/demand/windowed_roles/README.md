# windowed_roles: staffing plan

What it represents: the store's own staffing plan or a district "base schedule" template (dept, role,
which days, start, end, how many), the way leaders write it in a spreadsheet.

| File | Rows | Notes |
|---|---|---|
| `staffing_plan_ranges.csv` | 17 | `Days` = `Mon-Thu`, `Fri-Sun`, `Daily`, `Mon-Sun`, `Tue/Thu/Sat`; 24h times |
| `staffing_plan_per_day.csv` | 91 | The same plan expanded to one row per day, 12h times |
| `softlines_hardlines_plan.csv` | 28 | Only Softlines/Hardlines (the non-sales-driven roles), for mixing with sales_driven |
| `truck_override.csv` | 3 | Truck Unload Tue/Thu/Sat 04:00–09:00 × 5, for testing a second import |

**Importer support:**
- Per-day file: **works**. All columns auto-map; readiness green; solve 94.0% coverage, validator passed.
- Day ranges: **needs conversion.** `Days` isn't proposed for day ("Still needed: day"). Mapped by
  hand, every row is skipped ("bad date 'Mon-Thu'"), so no demand at all. Spec 2 in `../README.md`.
- Second import (e.g. `truck_override.csv` after the plan): today it **replaces the whole plan**, so
  only trucks remain. Spec 0: replace only Truck Unload on Tue/Thu/Sat.

In the UI: import `staffing_plan_per_day.csv` as Workload forecast. Try `staffing_plan_ranges.csv` to
see the skipped-rows problem (if commit-time warnings aren't shown yet, the card just looks
successful while the demand stays empty).
