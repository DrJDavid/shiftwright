# clean_small_tx: the happy path

15 team members, Store #2104 Round Rock TX (state law only). Three departments (Leadership, Front of
Store, General Merchandise), five roles (Leader on Duty, Guest Service Desk, Cashier, Drive Up, Softlines).
Tidy headers that all auto-map; times in 12h (`9:00 AM`); ISO dates; one 17-year-old cashier (no
federal hour limits at 16–17); three students available 3–9 pm on weekdays.

| File | Rows | Headers |
|---|---|---|
| roster.csv | 15 | Employee ID, Name, Department, Status, Wage, Birth Date, Hire Date, Phone, Min Hours, Max Hours |
| training.csv | 34 | Employee ID, Role (one row per skill) |
| availability.csv | 15 | Employee ID, Avail Mon..Avail Sun (`ALL`, `OFF`, `3:00 PM-9:00 PM`), Notes |
| forecast.csv | 49 | Role, Day (`Mon`), Start, End, Headcount (windowed blocks, 9 am–9 pm) |
| history.csv | 116 | Employee ID, Date, Start, End, Role (two past weeks) |

## In the UI
1. New store from the **empty** template, TX. In chat / store_basics card give: open 9:00–21:00 every
   day, 30-min slots, week of Mon Nov 9 2026 (`leader_setup.json`).
2. Drop roster → training → availability → forecast → history. Every column should map by itself
   (no "Still needed"). Roster shows the "Unknown department … added" note per department; training
   shows one "Unknown role … $0/h" per role. That's expected on an empty template.
3. Payroll 420 h/week. **Give every role a priority** (Leader on Duty 200, Guest Service Desk 40,
   Cashier 30, Drive Up 25, Softlines 20 $/h). Without this step every role is $0/h and the solver
   leaves the whole week empty (readiness doesn't catch it; see the top-level README).
4. Readiness: all green. Build the week: about 99.9% coverage, validator passes.

Variant: the same files into the **bigbox_small** template resolve to the template's roles (no "unknown
role" notes, priorities pre-filled), but readiness then says "Nobody trained for: hardlines,
fitting_room, grocery_stock" until those unused template roles are deleted.
