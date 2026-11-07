# WS3 status

**Done:**
- `federal.json`: FLSA weekly OT, $7.25 minimum wage, 14–15 hours (school / non-school weeks), HO 7 (no forklifts under 18).
- `states/TX.json`: min wage (= federal), 14–15 hours (Tex. Lab. Code § 51.013). No TX meal/rest/daily-OT law (in notes).
- `states/CA.json`: daily + weekly OT, two meal periods, rest periods (Wage Order 7), reporting-time pay, $16.90 min wage (2026), minors 14–15 and 16–17.
- Resolver `shiftwright_laws.resolve(jurisdiction | state, city=None) -> LawPack` + acceptance tests (`uv run pytest data/laws`).
- `python -m shiftwright_laws.coverage` prints the coverage table below.

**In progress:** predictive-scheduling cities, then the other states alphabetically.

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
- Minutes are minutes-from-midnight for times of day (420 = 7 a.m., 1140 = 7 p.m.).

**Shortcuts taken:**
- CA seventh-consecutive-day overtime is in `notes`, not params (no field for it).
- CA 16–17 school-week weekly cap: only the Lab. Code § 1391 48 h cap is encoded; Education Code permit limits not yet checked.
- Texas § 51.013 cited from TWC's official PDF copy of Chapter 51 (statutes site is a JS app that the fetcher can't read).

## Coverage (rule count per file × type; – = no rule; see each file's `notes` for "no such law")

| file | wOT | dOT | meal | rest | minor | minRole | clopen | predict | report | wage | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| federal | 1 | – | – | – | 2 | 1 | – | – | – | 1 | 3 |
| CA | 1 | 1 | 2 | 1 | 4 | – | – | – | 1 | 1 | 5 |
| TX | – | – | – | – | 2 | – | – | – | – | 1 | 4 |

