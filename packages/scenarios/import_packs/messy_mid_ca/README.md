# messy_mid_ca: what a real export looks like

25 people (24 import), Store 2291 Sacramento CA (state law: $16.90 minimum, meal/rest breaks, daily
OT, minor limits). Departments Leadership, Front End, Softlines, Hardlines, Flow. Job codes as role
names (LOD, GSA, CASHIER, DRIVE UP, SOFTLINES, HARDLINES, TRUCK, FORKLIFT). Truck Wed + Sat.

## Planted problems and what actually happens

| # | File | Planted | Expected / actual behaviour |
|---|---|---|---|
| 1 | roster | Junk columns `Store #`, `Email`, an unnamed trailing column, and **`Manager`** | Junk ignored. **Bug:** `Manager` is proposed as **age** (substring "age" in "Manager"). If the leader keeps it, every roster row is skipped (`could not convert string to float`). Set `Manager` → Ignore. |
| 2 | roster | Two blank rows (`,,,,,`) | 2 warnings "empty employee id; skipped" (commit-time, see bug B5) |
| 3 | roster | Dept spelled `Front End` / `FRONT END` / `front end` / `Front-End` | All merge into one `front_end` department (correct) |
| 4 | roster | DOB formats `02/15/1985`, `1991-09-17`, `31-Aug-1997`, `08/16/79` | All parsed (correct) |
| 5 | roster | 2223: DOB `7/4/62` | **Bug:** read as 2062 → **age −36**, no warning. The validator/engine then treat a 64-year-old as a minor. |
| 6 | roster | 2224: DOB `March 3, 1999` | Row skipped with "bad date" warning; 2224 then shows as "unknown employee" in training and availability |
| 7 | roster | Wages `$24.00`, `25.50`, `23.75/hr`, ` $ 26.00 `, `17.25` | All parsed (correct) |
| 8 | roster | 2212 at **$15.50** (below CA $16.90) | Readiness `minimum_wage` fails: "Below the $16.90/hr minimum (CA.minimum_wage.1): Remi Pemberly ($15.50)" |
| 9 | roster | 2207 appears twice ($17.00 then $18.25) | Last row wins ($18.25). **No duplicate warning.** |
| 10 | roster | 2225 phone `555-0185` (no area code) | **Bug:** stored as `+5550185`, no warning; outreach can't reach them |
| 11 | roster | Status `PT`, `Part Time`, `P/T`, `part-time`, `Seas` | PT variants → part_time (correct). **Bug:** 2213 `Seas` → part_time (only `season…`/`temp…` count as seasonal), no warning |
| 12 | training | `GSA; CASHIER` in one cell | Split into two roles (correct) |
| 13 | training | 2215 written as `2215.0` (Excel) | "unknown employee '2215.0'; skipped" → 2215 ends up trained on nothing |
| 14 | training | `9999` (not on roster) | "unknown employee" warning |
| 15 | training | **2219 is 16 and trained on FORKLIFT** | Imported. **Bug:** the new `forklift` role has no `powered_industrial_truck` tag and min_age 0, so the federal minor rule can't apply. **The engine actually scheduled 2219 on FORKLIFT and the validator passed it.** After the leader tags the role (role_tags + min_age 18), the engine uses adult 2220 instead and the validator passes. |
| 16 | training | `ZZ-TEMP` (no demand) | Added as a $0/h role with a warning; harmless |
| 17 | availability | `OFF`, `N/A`, blank, `ANY` | OFF / N/A = whole day unavailable; blank / ANY = available (correct) |
| 18 | availability | `9a-5p`, `4pm-10pm`, `8:00 AM - 12:00 PM, 5:00 PM - 9:00 PM` | Parsed, incl. the two-window day (correct) |
| 19 | availability | 2213 Mon `Not Available` | **Bug:** warning "could not read … left as available": the opposite of what it says |
| 20 | availability | 2214 `after 4pm` | Warning, left available (ok-ish: unreadable, flagged) |
| 21 | availability | blank row, `8888` (termed) | "unknown employee" warnings |
| 22 | availability | Headers `Weds`, `Thurs` | Mapped to Wed/Thu (correct) |
| 23 | forecast | Day as `Mon`, `Tuesday`, `2026-11-11`, `Thurs`, `11/13/2026`, `Sat`, `Sunday` | All seven days resolved (correct) |
| 24 | forecast | One row per **hour** with only a `Time` column | **Bug:** each row becomes a 30-min block (store slot), so demand is 8:00–8:30, 9:00–9:30, …: **half the hours are missing**, silently |
| 25 | forecast | `HC` `1.5` and `0.5` | **Bug:** truncated to 1 and 0 (the 0.5 row is dropped) with no warning |
| 26 | forecast | `BEAUTY` (nobody trained) | Role added with warning; readiness `training` fails "Nobody trained for: beauty" |
| 27 | history | Kronos report title + run line + blank line **above the header** | Preview shows one column ("Kronos Workforce Central - Punch Detail Report") and all four required fields missing; commit refused (422). Delete the top 3 lines and re-upload. |

## In the UI
1. Empty template, CA. Open 08:00–22:00 daily, 30-min slots, pre-open 180 min, America/Los_Angeles.
2. Roster: set **Manager → Ignore** before importing. Training / availability / forecast map by themselves.
   History will not import as-is (row 27).
3. Payroll 700 h, priorities in `leader_setup.json`.
4. Readiness should be **red** with exactly two blockers: minimum wage (2212) and "Nobody trained for: beauty".
5. Fix like a leader would (`fixes_after_review` in `leader_setup.json`): 2212 → $17.00, 2223 age 64,
   2225 phone, train 2211 + 2213 on Beauty, 2215 on Hardlines + Truck. Readiness turns green.
6. **Tag FORKLIFT as a powered industrial truck role (min age 18).** There's no card for this today;
   it needs a PUT /config or a chat mutation. Without it, the 16-year-old gets scheduled on the forklift.
