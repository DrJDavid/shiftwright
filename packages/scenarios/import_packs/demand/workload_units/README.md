# workload_units: truck / freight

What it represents: the DC's truck schedule (date, truck, scheduled arrival, cases, pieces) and the
store's unload standard. The leader turns cases into a crew and a start time.

| File | Shape |
|---|---|
| `trucks_normal.csv` | Tue 2,880 · Thu 2,880 · Sat 3,240 cases, arrival 04:00 |
| `trucks_holiday.csv` | Mon 3,600 · Tue 3,600 · Wed 4,320 · Sat 3,240 cases (no truck Thanksgiving / Black Friday) |
| `unload_standards.csv` | Truck Unload, driver `cases`, 180 cases per labor hour, crew 3–6, finish within 4 h (synthetic standard, not law) |

Pieces = cases × 7 (informational).

**Importer support: unsupported.** As a Workload forecast: "Still needed: role, start, headcount",
commit 422. Dangerous today: if the leader forces `Origin` → role, `Sched Arrival` → start,
`Cases` → headcount, the importer creates a new role `dc_0553` needing **2,880 people**, with no
plausibility warning.

**Wanted (Spec 5 in `../README.md`):** import `labor_standards` (this file), then `workload`:
labor h = cases / 180; crew = clamp(ceil(labor h / 4), 3, 6); duration = labor h / crew rounded up
to the slot. Normal week → Tue/Thu 4 people 04:00–08:00, Sat 5 people 04:00–08:00. Holiday Wed
4,320 cases → 6 people 04:00–08:00. It should also add the truck Event. Pinned by
`test_workload_convert[*]` (xfail).

In the UI today: tell the chat the truck days and times (an Event) and enter the crew through the
staffing card or a staffing-plan row instead.
