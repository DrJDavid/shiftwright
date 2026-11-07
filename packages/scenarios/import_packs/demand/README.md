# Demand import packs (corporate labor models)

Mock corporate **demand** exports, separate from rosters, in the five styles a big-box store leader
actually receives. All are for **Store T2290 Katy TX** and use the roles and departments of
[`../corporate_mid_tx`](../corporate_mid_tx/README.md) (Leader on Duty, Cashier, Guest Service,
Softlines, Hardlines, Drive Up, Order Pick, Truck Unload), so they import on top of that pack's
roster/training/availability and can be mixed.

Every file comes from one synthetic "truth" per week (hourly transactions, online orders, truck
cases) plus one set of labor standards (`build_demand.py`, reference math in `spec_reference.py`).
So all five styles describe the **same store-week**: the department hours add up to the per-slot
headcount-hours, the trucks match the per-slot truck rows, and so on. The labor standards are
invented corporate planning numbers, **not law**.

| Sub-pack | Style | Today |
|---|---|---|
| [per_slot_headcount/](per_slot_headcount/README.md) | UKG/Kronos labor forecast: job × date × 15/30-min interval → headcount | **Works**: 30-min; 15-min in a 15-min store; 15-min into a 30-min store aggregates to the peak (Spec 1b, done by WS6) |
| [windowed_roles/](windowed_roles/README.md) | Staffing plan: dept, role, days, start, end, headcount | **Works one row per day.** Day ranges (`Mon-Thu`, `Daily`, `Tue/Thu/Sat`): `Days` isn't auto-mapped; mapped by hand, every row is skipped |
| [dept_daily_hours/](dept_daily_hours/README.md) | Labor allocation: department × day → budgeted hours, week total | **Unsupported** (no role/time/headcount). Spec 3 below |
| [sales_driven/](sales_driven/README.md) | Hourly transactions / sales / online orders + labor standards | **Unsupported.** Spec 4 below |
| [workload_units/](workload_units/README.md) | Truck schedule: date, arrival, cases + unload standard | **Unsupported**; forcing a mapping creates a 2,880-person requirement. Spec 5 below |

## Week variants

`week_variants.json` holds what the leader gives the store_basics card for each week (week start,
open hours per day; pre-open 240 min so the 4 am truck can be staffed) and the truth's total
headcount-hours (used as the payroll cap in the tests).

| Variant | Week | Shape | Truth hours |
|---|---|---|---|
| `normal` | Mon Nov 9 2026 | 8 am–10 pm daily, weekend peak, trucks Tue/Thu/Sat | 949 |
| `holiday` | Mon Nov 23 2026 | Thanksgiving Thu **closed**, Black Friday 6 am–11 pm with doorbuster mornings, Sat 7 am–11 pm, 4 trucks (Mon/Tue/Wed/Sat, heavier) | 1,078 |
| `promo` | Mon Nov 16 2026 | Weekend deals Fri–Sun (+30–75% transactions, online ×1.7–1.9) | 1,013 |
| `light_january` | Mon Jan 11 2027 | −20–35% traffic, Sun 10 am–8 pm, 2 trucks | 765 |

Per-slot (30-min) files exist for all four weeks, 15-min for normal + holiday; department hours and
sales for all four; trucks for normal + holiday.

## In the UI
1. Onboard `corporate_mid_tx` first (roster with `Home Org` → home department, training, availability).
   Set the week and hours from `week_variants.json` (e.g. holiday: Thu closed, Fri 6:00–23:00).
2. Drop one demand file as **Workload forecast**. What should happen is in each sub-pack README.
3. Importing a second forecast file today **replaces all corporate demand** (not just that file's roles).
   To mix styles you currently can't import truck rows after a staffing plan (Spec 0 fixes that).

## Verification (TestClient, real engine + validator, re-run Sat Nov 7 2026 on main @ 8020045, after WS6's importer fixes)

`uv run pytest packages/scenarios/import_packs/demand -rxX` (about 60 s; the three 20 s solves are `@pytest.mark.slow`, skip with `-m "not slow"`).

| Test | Result today |
|---|---|
| per-slot 30-min, 4 weeks | Demand equals the truth exactly; no skipped rows, no unknown roles; readiness ready |
| per-slot 15-min in a 15-min store, normal + holiday | Exact |
| per-slot 15-min into a 30-min store | Peak per 30-min slot (Spec 1b): exact |
| Solve, per-slot normal | feasible, 120 shifts, **91.5% coverage**, 871.5 h, validator passed |
| Solve, per-slot holiday | feasible, 127 shifts, **86.2% coverage**, 934 h, validator passed (Black Friday outruns 40 people: expected) |
| Solve, windowed per-day normal | feasible, 106 shifts, **94.0% coverage**, 820 h, validator passed |
| windowed with day ranges | `Days` not proposed → "Still needed: day", commit 422. Mapped by hand: all 17 rows skipped ("bad date 'Mon-Thu'"), no demand |
| dept hours / sales / trucks / standards as forecast | Preview "Still needed" role/day/start/headcount; commit 422 |
| `labor_model.csv` as forecast | `Window Start`/`End` → start/end (whole-word matching); day + headcount still needed, 422 |
| `Units per Staff Hour` as forecast | proposed as headcount |
| Trucks with forced mapping | Requirement of **2,880 people** for new role `dc_0553`, accepted |
| Second forecast import | Wipes the first one's demand |

xfail (spec, for WS6): day ranges (1), replace by role-day (1), dept hours ×4,
sales ×4, trucks ×2, all five styles mixed = per-slot truth (1), absurd-headcount warning (1).

---

# Conversion spec for WS6

Shared conventions:
- Output is `DemandRequirement`s with `source: "corporate"` and a `note` naming the file and style
  (e.g. `"labor_hours: FULFILLMENT 32.0 h, Drive Up 50%"`). Adjacent equal slots merge, as today.
- Times are on the store slot grid (`Store.slot_minutes`), days are 0–6 from `Store.week_start`.
  Dated rows outside the schedule week: warn and skip (not `% 7`).
- **Spec 0, replacement scope:** a demand import replaces existing corporate demand **only for the
  (role, day) pairs it produces**. Leader and event demand are never touched. (Today: all corporate demand.)
- **Plausibility:** warn when one requirement's headcount exceeds the number of employees trained for
  the role (or 50 if no one is trained yet).
- New import kinds (proposal; names are constants at the top of `test_demand.py`): `labor_model`,
  `labor_hours`, `labor_standards`, `sales_forecast`, `workload`. These need a contracts/API.md change
  (`ImportKind`) and the web card's kind list (WS7). `labor_model` and `labor_standards` are stored per
  store (kv), upserted by role, and shown in the preview/commit like any import.
- Rounding choices below (ceil for standards, round-half-up for hours) are planning conventions, not law.
  The README should say so in the UI where it shows the conversion.

## Spec 1b: per-slot rows whose interval ≠ store slot (implemented on main)
- Interval length = the `interval_minutes` column if mapped (new optional forecast field; synonyms
  `interval (min)`, `interval length`, `length`, `duration`, `mins`), else `end − start` if End is
  mapped, else the smallest positive gap between consecutive starts for the same role and day.
- Interval **finer** than the slot (15-min file, 30-min store): headcount for a slot = **max** over the
  sub-intervals it contains (cover the peak; the leader can lower it). Expected:
  `test_per_slot_15min_into_30min_store_takes_peak`.
- Interval **coarser** (hourly rows): the row covers `[start, start + interval)` (fixes the "half the
  hours missing" bug).

## Spec 2: day ranges in windowed plans
`Days` values: `Mon-Fri`, `Fri-Mon` (wraps), `Sat,Sun`, `Tue/Thu/Sat`, `Mon & Wed`, `Daily`, `All`,
`Every day`, `Mon-Sun`; one requirement per listed day. End ≤ start means overnight (+1440).
Reference: `spec_reference.parse_days` / `windows_to_slots`.

## Spec 3: department daily hours → headcount
Inputs:
- `labor_hours`: wide (`Dept`, one column per day headed `Mon 11/09` / `Monday` / a date, optional
  `Week Total`) or long (`dept`, `day`, `hours`). A row whose dept is `TOTAL` / `Store Total` is the
  store total.
- `labor_model` (`Dept`, `Role`, `Share %`, `Window Start`, `Window End`): how each department's
  hours split across roles and when each role works. Window blank = store open..close that day; a
  window may reach into pre-open (Truck Unload 04:00–10:00).
- If there's no model row for a department: if exactly one config role belongs to that department,
  100% / open..close; otherwise warn "need a labor model for <dept>" and skip it.

Per department-day with hours `H > 0` on an open day (hours on a closed day: warn, drop), and per
model role:
1. `role_hours = H × share / 100`
2. `units = round_half_up(role_hours × 60 / slot)` (headcount-slots)
3. slots = `[window_start, window_end)` stepped by slot
4. **Spread `units` over the slots by cumulative rounding**: slot *i* gets
   `round_half_up(units × i/n) − round_half_up(units × (i−1)/n)` (flat). It's exact (sums to
   `units`), deterministic, and spreads remainders evenly. Use exact arithmetic.
5. Optional v2 (not tested): weight slots by the stored sales curve for that day (transactions in the
   hour containing the slot) for roles whose standard is transactions/sales-driven; same cumulative
   rounding with weights. Never invent a curve.

Totals: per-dept `Week Total` ≠ sum of days by more than 0.05 h → warning. The store TOTAL's week
figure sets `budget.weekly_hours_cap` **only if it is 0**, otherwise warn when it differs.
Caveat to show the leader: corporate hours are payroll hours, so treating them as headcount-hours
ignores unpaid meal time (coverage will look slightly short in CA). Reference:
`spec_reference.labor_hours_to_slots`; expected by `test_dept_hours_convert[*]`.

## Spec 4: sales / transactions forecast + labor standards
- `labor_standards` fields: `role`, `driver` (`transactions` | `sales` | `online_orders` | `cases` |
  `pieces` | `fixed`), `units_per_staff_hour`, `min_hc`, `max_hc`, `max_duration_hours` (workload only).
- `sales_forecast` fields: `day`/`date`, `hour` (start of hour), any of `transactions`, `sales`,
  `online_orders`.
- Per hour row on an open day, per non-workload standard:
  `hc = clamp(ceil(driver_value / units_per_staff_hour), min_hc, max_hc)`; `fixed` → `min_hc`.
  Applied to every slot in `[hour, hour + 60) ∩ [open, close)`. Rows outside open hours: ignored
  (warning if the driver is > 0). Driver column missing: warn, skip that role.
- No standards stored yet → 422 "Import labor standards first."
Reference: `spec_reference.sales_to_slots`; expected by `test_sales_convert[*]`.

## Spec 5: truck / freight workload
- `workload` fields: `day`/`date`, `arrival`, `cases` (or `pieces`), optional `truck_id`. Uses the
  standard whose driver is `cases`/`pieces` (role Truck Unload here: 180 cases per labor hour, crew
  3–6, finish within 4 h).
- Per truck: `labor_h = cases / units_per_staff_hour`;
  `crew = clamp(ceil(labor_h / max_duration_hours), min_hc, max_hc)`;
  `duration = ceil_to_slot(labor_h × 60 / crew)` minutes; demand `crew` from `arrival` to
  `arrival + duration`. Trucks overlapping on one day add up. Example: 2,880 cases → 16 labor h →
  crew 4 → 04:00–08:00; 4,320 → 24 h → crew 6 → 04:00–08:00; 3,240 → 18 h → crew 5 → 3.6 h → 04:00–08:00.
- Should also add/update a `truck` Event for that window. Arrival earlier than open − pre-open: warn
  (it can't be staffed).
Reference: `spec_reference.workload_to_slots`; expected by `test_workload_convert[*]`.

`test_full_week_from_mixed_styles`: standards + sales + softlines/hardlines plan + trucks must equal
the 30-min per-slot file exactly. That's the proof the styles agree.

## Not supported (no files)
Wide per-slot forecasts (one column per time interval), multi-store files (a `Location` column with
more than one store; should refuse or ask which store), `.xlsx`, weekly-only hour totals with no day split.
