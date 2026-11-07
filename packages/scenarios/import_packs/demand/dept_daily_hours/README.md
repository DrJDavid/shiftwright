# dept_daily_hours: corporate labor allocation (the realistic big-box format)

What it represents: the weekly payroll allocation corporate sends a store: **hours, not people**, per
department per day, with a week total. The leader turns this into a schedule in their head. This is
the format a Target-style store actually lives by.

| File | Shape |
|---|---|
| `labor_hours_{normal,holiday,promo,light_january}.csv` | `Dept, Mon 11/09, …, Sun 11/15, Week Total` + a `TOTAL` row. 7 departments (LEADERSHIP, FRONT END, GUEST SERVICE, SOFTLINES, HARDLINES, FULFILLMENT, FLOW). Holiday: Thu = 0.0 (closed) |
| `labor_model.csv` | `Dept, Role, Share %, Window Start, Window End`: FULFILLMENT is 50% Drive Up / 50% Order Pick, Softlines/Hardlines work 09:00–18:00, Truck Unload 04:00–10:00, others the store's open hours |

The hours are the per-slot truth summed by department (e.g. normal week: 949.0 h, FRONT END 257.0 h).

**Importer support: unsupported.** As a Workload forecast the preview says "Still needed: role, day,
start, headcount" and the commit is refused (422). `labor_model.csv` maps `Window Start`/`End` to start/end but still lacks day and headcount (422).

**Wanted (Spec 3 in `../README.md`):** import `labor_model` then `labor_hours`; each department-day's
hours split by share, turned into headcount-slots (round half up) and spread evenly over the role's
window by cumulative rounding; week total sets the payroll cap if unset. Expected results are pinned
by `test_dept_hours_convert[*]` (xfail) using `spec_reference.labor_hours_to_slots`. The flat spread
won't reproduce the per-slot file's evening cashier peak. That needs the optional sales-curve weighting.
