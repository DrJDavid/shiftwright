# WS3 status

**Done:**
- `federal.json`: FLSA weekly OT, $7.25 minimum wage, 14–15 hours (school / non-school weeks), HO 7 (no forklifts under 18).
- `states/TX.json`: min wage (= federal), 14–15 hours (Tex. Lab. Code § 51.013). No TX meal/rest/daily-OT law (in notes).
- `states/CA.json`: daily + weekly OT, two meal periods, rest periods (Wage Order 7), reporting-time pay, $16.90 min wage (2026), minors 14–15 and 16–17.
- Resolver `shiftwright_laws.resolve(jurisdiction | state, city=None) -> LawPack` + acceptance tests (`uv run pytest data/laws`).
- `python -m shiftwright_laws.coverage` prints the coverage table below.

- Cities (`cities/_index.json`): Austin (no rules — Tex. Lab. Code § 1.005 preemption), Seattle, Chicago, Evanston, New York City, Philadelphia, San Francisco, Los Angeles, Berkeley, Emeryville. All predictive-scheduling ordinances from official city sources (high), except Evanston's predictability-pay hours (low, excluded by default).
- Oregon statewide predictive scheduling + rest between shifts (BOLI, high).
- All 48 remaining states + DC drafted from US DOL WHD tables (`medium`): minimum wage (table updated 2026-11-05), weekly/daily overtime, meal and rest periods (tables revised 2023-01-01). States with no such law say so in `notes`.

- **State minor-hour limits (2026-11-06 slice, all `high`, primary sources):** NY (Lab. Law §§ 142-143), FL (§ 450.081), IL (820 ILCS 206), PA (Child Labor Act § 3), OH (R.C. 4109.07), NC (G.S. 95-25.5), MI (MCL 409.110-.111), NJ (N.J.S.A. 34:2-21.3), WA (WAC 296-125-101, eff. 2026-07-01), AZ (A.R.S. § 23-233), MA (c. 149 §§ 65-67), TN (TDLWD page), MD (§ 3-211), MO (RSMo 294.030), WI (§ 103.68), MN (§ 181A.04). Each band has `school_week` true/false variants, except where state law only limits school weeks (FL/OH/NC/TN/MN 16-17; listed in `tests/test_state_minors.py::SCHOOL_WEEK_ONLY`). Where the law is identical in both (MA, MN, MO under-16) the two variants carry the same numbers.
- Researched, no state hour limits beyond federal (note only, starts `Minors researched`): GA (GDOL), VA (§ 40.1-80.1 incorporates FLSA), IN (Indiana DOL, mirrors federal since 2025).
- Wage/OT/meal upgraded to primary sources with statutory effective dates: NY + NYC (§ 652(1-a), eff. 2026-01-01), FL ($15 eff. 2026-09-30, Fla. Const. art. X § 24), IL (wage, OT, 2 meal periods, ILCS), MI ($13.73 eff. 2026-01-01 + $15 eff. 2027-01-01), VA ($12.77 eff. 2026-01-01 + $13.75 eff. 2027-01-01), NJ ($16.48 eff. 2027-01-01 added; 2026 rate still DOL). Future-dated rates are ignored by the resolver until in effect (test in `test_state_minors.py`).

**In progress / next:** CO minors (CDLE youth page links to INFO #22 / 7 CCR 1103-20, neither fetched; C.R.S. is Lexis-hosted) — not done. Remaining DOL-drafted wage effective dates (OH page is a JS portal; PA = $7.25 federal; NJ 2026). `minor_prohibited_roles` beyond HO 7: none encoded (only role tag in use is `powered_industrial_truck`; GA/WA/MD prohibited lists noted in notes). Remaining 30 states' minor limits.

**Blocked on:** nothing.

**Resolver merge policy (for engine/validator):**
- Weekly OT, daily OT, minimum wage: exactly one rule kept per type — the most protective (lower threshold / higher wage; ties → more local). Future-dated wages are ignored until in effect.
- Every other type is a limit and is *stacked*: all federal/state/city rules are returned, each with its own citation. Enforce all of them (= the strictest). E.g. TX returns both federal 14–15 (18 h school week) and TX 14–15 (48 h) rules.
- Unknown state → `federal_fallback` + warning; city with no file → `state_only` + warning; `confidence == "low"` excluded unless `include_low_confidence=True`.
- Data dir defaults to `data/laws/` (from the editable install); override with env `SHIFTWRIGHT_LAWS_DIR` if deployed as a wheel.

**Extra param keys (beyond the contract docstring; `params` is a free dict):**
- `minor_limits.max_hours_non_school_day` — cap on a non-school day inside a school week (federal, CA). Without it, `max_hours_day` in a school-week rule is the school-day cap.
- `minor_limits.latest_end_before_non_school_day` — CA 16–17 may work to 12:30 a.m. (1470) before a non-school day.
- `rest_break.not_required_under_minutes` (CA: 210), `reporting_time_pay.max_paid_hours` (CA: 4).
- `predictive_scheduling`: `reduced_hours_fraction` (pay for cut hours, e.g. 0.5), `change_premium_hours_max`, `change_premium_hours_under_24h`, `change_premium_window_days`, `changes_restricted_within_notice` + `on_call_prohibited` (NYC: prohibitions, no premium), `min_locations`.
- `min_rest_between_shifts`: `premium_applies_to: "shift"` = whole next shift at the premium (Chicago, LA); absent = only hours inside the rest window. `premium_flat_dollars` (Philadelphia $40, `premium_multiplier: null`).
- `minor_limits.max_days_week` (NY, FL, PA, MI, NJ, WA, MA, MO, WI: 6) and `minor_limits.max_avg_hours_day` (MI 16-17: 8) — informational; the validator does not check them yet.
- `minor_limits.latest_end_before_non_school_day` is also used by WA, MI, AZ, MA (Fri/Sat nights).
- `meal_break.earliest_start_minute_of_shift`, `meal_break.employee_optional` (ND), `rest_break.max_minutes_without_rest` (WA: 180), `daily_overtime.applies_if_rate_below_min_wage_multiple` (NV: 1.5).
- Minutes are minutes-from-midnight for times of day (420 = 7 a.m., 1140 = 7 p.m.).

**Shortcuts taken:**
- DOL-drafted states: `minimum_wage.effective` = DOL table date (2026-11-05), not the statutory date (fixed for NY, FL, IL, MI, VA). Minor-hour limits not yet researched for states not listed above (federal floor applies; their notes say so).
- Minor-specific meal/rest breaks (e.g. 30 min after 5 h in PA/OH/MI/IL/NC/VA/MD; 6 h in NJ/WI/TN) are in notes only — `meal_break` has no age scope.
- Validator convention Mon-Fri = school days makes Friday-night/day rules stricter than law in NY, FL, WA, TN, OH, NC, MN (noted per state). NJ 16-17 summer 10 h / 50 h allowance not encoded (year-round 8 h / 40 h enforced). TN source is the TDLWD summary page (statute is Lexis-hosted); its 3 h/day school-week cap is applied to Saturdays too — verify.
- Maryland retail shift breaks: DOL table does not say paid/unpaid; encoded rest=paid, meal=unpaid, flagged in notes.
- City aliases ("nyc", "new york city") are not mapped; the city key is `new york`.
- CA seventh-consecutive-day overtime is in `notes`, not params (no field for it).
- CA 16–17 school-week weekly cap: only the Lab. Code § 1391 48 h cap is encoded; Education Code permit limits not yet checked.
- Texas § 51.013 cited from TWC's official PDF copy of Chapter 51 (statutes site is a JS app that the fetcher can't read).

## Coverage (rule count per file × type; – = no rule; see each file's `notes` for "no such law")

| file | wOT | dOT | meal | rest | minor | minRole | clopen | predict | report | wage | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| federal | 1 | – | – | – | 2 | 1 | – | – | – | 1 | 3 |
| AK | 1 | 1 | – | – | – | – | – | – | – | 1 | 6 |
| AL | – | – | – | – | – | – | – | – | – | – | 7 |
| AR | 1 | – | – | – | – | – | – | – | – | 1 | 7 |
| AZ | – | – | – | – | 2 | – | – | – | – | 1 | 7 |
| CA | 1 | 1 | 2 | 1 | 4 | – | – | – | 1 | 1 | 5 |
| CO | 1 | 1 | 1 | 1 | – | – | – | – | – | 1 | 4 |
| CT | 1 | – | 1 | – | – | – | – | – | – | 1 | 5 |
| DC | 1 | – | – | – | – | – | – | – | – | 1 | 6 |
| DE | – | – | 1 | – | – | – | – | – | – | 1 | 6 |
| FL | – | – | – | – | 3 | – | – | – | – | 1 | 11 |
| GA | – | – | – | – | – | – | – | – | – | – | 8 |
| HI | 1 | – | – | – | – | – | – | – | – | 1 | 6 |
| IA | – | – | – | – | – | – | – | – | – | 1 | 7 |
| ID | – | – | – | – | – | – | – | – | – | 1 | 7 |
| IL | 1 | – | 2 | – | 2 | – | – | – | – | 1 | 9 |
| IN | 1 | – | – | – | – | – | – | – | – | 1 | 8 |
| KS | – | – | – | – | – | – | – | – | – | 1 | 7 |
| KY | 1 | – | – | 1 | – | – | – | – | – | 1 | 6 |
| LA | – | – | – | – | – | – | – | – | – | – | 7 |
| MA | 1 | – | 1 | – | 4 | – | – | – | – | 1 | 6 |
| MD | 1 | – | 1 | 1 | 2 | – | – | – | – | 1 | 6 |
| ME | 1 | – | 1 | – | – | – | – | – | – | 1 | 6 |
| MI | 1 | – | – | – | 4 | – | – | – | – | 2 | 7 |
| MN | 1 | – | – | – | 3 | – | – | – | – | 1 | 7 |
| MO | 1 | – | – | – | 2 | – | – | – | – | 1 | 7 |
| MS | – | – | – | – | – | – | – | – | – | – | 7 |
| MT | 1 | – | – | – | – | – | – | – | – | 1 | 7 |
| NC | 1 | – | – | – | 3 | – | – | – | – | 1 | 7 |
| ND | 1 | – | 1 | – | – | – | – | – | – | 1 | 5 |
| NE | – | – | – | – | – | – | – | – | – | 1 | 7 |
| NH | 1 | – | 1 | – | – | – | – | – | – | 1 | 5 |
| NJ | 1 | – | – | – | 4 | – | – | – | – | 2 | 10 |
| NM | 1 | – | – | – | – | – | – | – | – | 1 | 7 |
| NV | 1 | 1 | 1 | 1 | – | – | – | – | – | 1 | 3 |
| NY | 1 | – | 1 | – | 4 | – | – | – | – | 1 | 10 |
| OH | 1 | – | – | – | 3 | – | – | – | – | 1 | 9 |
| OK | – | – | – | – | – | – | – | – | – | 1 | 7 |
| OR | 1 | – | 1 | 1 | – | – | 1 | 1 | – | 1 | 8 |
| PA | 1 | – | – | – | 4 | – | – | – | – | 1 | 8 |
| RI | 1 | – | 2 | – | – | – | – | – | – | 1 | 7 |
| SC | – | – | – | – | – | – | – | – | – | – | 7 |
| SD | – | – | – | – | – | – | – | – | – | 1 | 7 |
| TN | – | – | 1 | – | 3 | – | – | – | – | – | 8 |
| TX | – | – | – | – | 2 | – | – | – | – | 1 | 5 |
| UT | – | – | – | – | – | – | – | – | – | 1 | 7 |
| VA | – | – | – | – | – | – | – | – | – | 2 | 8 |
| VT | 1 | – | – | – | – | – | – | – | – | 1 | 8 |
| WA | 1 | – | 1 | 1 | 4 | – | – | – | – | 1 | 6 |
| WI | 1 | – | – | – | 2 | – | – | – | – | 1 | 7 |
| WV | 1 | – | 1 | – | – | – | – | – | – | 1 | 6 |
| WY | – | – | – | – | – | – | – | – | – | – | 7 |
| ca-berkeley | – | – | – | – | – | – | 1 | 1 | – | 1 | 3 |
| ca-emeryville | – | – | – | – | – | – | 1 | 1 | – | 1 | 4 |
| ca-los-angeles | – | – | – | – | – | – | 1 | 1 | – | 1 | 3 |
| ca-san-francisco | – | – | – | – | – | – | – | 1 | – | 1 | 4 |
| il-chicago | – | – | – | – | – | – | 1 | 1 | – | 1 | 4 |
| il-evanston | – | – | – | – | – | – | – | 1 | – | – | 3 |
| ny-new-york | – | – | – | – | – | – | – | 1 | – | 1 | 5 |
| pa-philadelphia | – | – | – | – | – | – | 1 | 1 | – | – | 4 |
| tx-austin | – | – | – | – | – | – | – | – | – | – | 4 |
| wa-seattle | – | – | – | – | – | – | 1 | 1 | – | 1 | 4 |
