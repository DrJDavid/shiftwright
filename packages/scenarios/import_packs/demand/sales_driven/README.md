# sales_driven: hourly sales forecast + labor standards

What it represents: the inputs corporate's labor model uses: an hourly forecast of transactions, net
sales and online orders, and the store's labor standards (how many of each driver one person handles
per hour, with min/max headcount).

| File | Shape |
|---|---|
| `sales_{normal,holiday,promo,light_january}.csv` | `Store, Date, Hour, Transactions, Net Sales, Online Orders`, one row per open hour (holiday: no Thursday rows; Black Friday from 06:00 with doorbuster mornings) |
| `labor_standards.csv` | Leader on Duty fixed 1; Cashier 40 transactions/staff-hour (1–8); Guest Service 160 (1–3); Drive Up 12 online orders (1–4); Order Pick 12 online orders (0–4) |

Standards are synthetic planning numbers, not law. Net Sales = transactions × $48.50 (synthetic).
Softlines/Hardlines aren't sales-driven here: mix with `../windowed_roles/softlines_hardlines_plan.csv`.
Trucks come from `../workload_units`.

**Importer support: unsupported.** As a Workload forecast: sales preview "Still needed: role, start,
headcount", standards preview proposes `Units per Staff Hour` → headcount; both commits refused (422).

**Wanted (Spec 4 in `../README.md`):** import `labor_standards` once, then `sales_forecast` per week:
`hc = clamp(ceil(driver / per), min, max)` per hour, applied to that hour's slots within open hours.
`test_sales_convert[*]` (xfail) pins the result. With standards + sales + the softlines/hardlines plan
+ trucks, the result must equal `../per_slot_headcount/forecast_30min_normal.csv` exactly
(`test_full_week_from_mixed_styles`).
