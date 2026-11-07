# WS3 status

**Done:**
- `federal.json`: FLSA weekly OT, $7.25 minimum wage, 14–15 hours (school / non-school weeks), HO 7 (no forklifts under 18).
- `states/TX.json`: min wage (= federal), 14–15 hours (Tex. Lab. Code § 51.013). No TX meal/rest/daily-OT law (in notes).
- `states/CA.json`: daily + weekly OT, two meal periods, rest periods (Wage Order 7), reporting-time pay, $16.90 min wage (2026), minors 14–15 and 16–17.
- Resolver `shiftwright_laws.resolve(jurisdiction | state, city=None) -> LawPack` + acceptance tests (`uv run pytest data/laws`).
- `python -m shiftwright_laws.coverage` prints the coverage table below.

- Cities (`cities/_index.json`): Austin (no rules — Tex. Lab. Code § 1.005 preemption), Seattle, Chicago, Evanston, New York City, Philadelphia, San Francisco, Los Angeles, Berkeley, Emeryville. All predictive-scheduling ordinances from official city sources (high), except Emeryville (medium: city site blocked re-verification on 2026-11-07; exemptions not encoded). Premium params + call-in exemptions completed for all 10 Fair Workweek jurisdictions on 2026-11-07 (SEMANTICS #17; `tests/test_predictive_scheduling.py`).
- Oregon statewide predictive scheduling + rest between shifts (BOLI, high).
- All 48 remaining states + DC drafted from US DOL WHD tables (`medium`): minimum wage (table updated 2026-11-05), weekly/daily overtime, meal and rest periods (tables revised 2023-01-01). States with no such law say so in `notes`.

- **State minor-hour limits (2026-11-06 slice, all `high`, primary sources):** NY (Lab. Law §§ 142-143), FL (§ 450.081), IL (820 ILCS 206), PA (Child Labor Act § 3), OH (R.C. 4109.07), NC (G.S. 95-25.5), MI (MCL 409.110-.111), NJ (N.J.S.A. 34:2-21.3), WA (WAC 296-125-101, eff. 2026-07-01), AZ (A.R.S. § 23-233), MA (c. 149 §§ 65-67), TN (TDLWD page), MD (§ 3-211), MO (RSMo 294.030), WI (§ 103.68), MN (§ 181A.04). Each band has `school_week` true/false variants, except where state law only limits school weeks (FL/OH/NC/TN/MN 16-17; listed in `tests/test_state_minors.py::SCHOOL_WEEK_ONLY`). Where the law is identical in both (MA, MN, MO under-16) the two variants carry the same numbers.
- Researched, no state hour limits beyond federal (note only, starts `Minors researched`): GA (GDOL), VA (§ 40.1-80.1 incorporates FLSA), IN (Indiana DOL, mirrors federal since 2025).
- Wage/OT/meal upgraded to primary sources with statutory effective dates: NY + NYC (§ 652(1-a), eff. 2026-01-01), FL ($15 eff. 2026-09-30, Fla. Const. art. X § 24), IL (wage, OT, 2 meal periods, ILCS), MI ($13.73 eff. 2026-01-01 + $15 eff. 2027-01-01), VA ($12.77 eff. 2026-01-01 + $13.75 eff. 2027-01-01), NJ ($16.48 eff. 2027-01-01 added; 2026 rate still DOL). Future-dated rates are ignored by the resolver until in effect (test in `test_state_minors.py`).

- **Second slice (2026-11-06, all `high`):** CO (CDLE INFO #22A, C.R.S. § 8-12-105; 7 CCR 1103-20 has no hour limits), AL (Dept. of Workforce poster), LA (R.S. 23:211-215), KY (803 KAR 1:100), OR (BOLI), OK (OK DOL brochure), CT (§§ 31-13/14/23, mercantile; under-16 retail essentially barred), UT (§ 34-23-202), IA (§ 92.7), NV (NRS 609.240), AR (DOLL page), KS (K.S.A. 38-603), NE (§ 48-310), ID (§ 44-1304), NH (RSA 276-A:4), ME (26 M.R.S. § 774), RI (§ 28-3-11), DE (19 Del. C. § 506), SD (SDCL 60-12-1), WV (§ 21-6-7), DC (§ 32-202), WY (§ 27-6-110), ND (§ 34-07-15), AK (AS 23.10.340), HI (HRS § 390-2), MT (MCA 41-2-115 via DLI). SC researched: S.C. Code § 41-13-20 forbids stricter-than-federal rules (note only).
- TN 14-15 re-checked against the TDLWD required poster quoting T.C.A. § 50-5-104: school-week non-school days are capped at 8 h (fixed), 9 p.m. before non-school days.

- **v1.5 slice (2026-11-07):** `tipped_minimum_wage` for federal ($2.13 / $5.12 credit, 29 CFR 531.50), TX (§ 62.052 adopts FLSA), IL ($9.00, 40% credit, 820 ILCS 105/4(c)), Chicago ($12.96 from 2026-07-01, chicago.gov); CA, WA, Seattle: no tip credit (notes, no rule). Federal hazardous orders HO 2/7/10/11/12/14 and the 14-15 limits (29 CFR 570.33-.34) mapped to ROLE_TAGS; IL under-16 alcohol handling, ladders/scaffolds, power saws (820 ILCS 206/40). `applies_to` verified on every Fair Workweek rule (SF corrected to both); food-sector thresholds; `excludes_same_day_split` set for Chicago, Seattle, Philadelphia, Oregon, LA (Berkeley, Evanston, Emeryville: not set); `exemption_applies_to` on all Fair Workweek rules.
- **Resolver tipped policy:** one `tipped_minimum_wage` rule, highest cash wage, ties to the more local level, and only from a level at or below the level whose `minimum_wage` rule won. So a state with its own minimum wage but no researched tipped rule gets NO tipped rule (tipped employees owed the full minimum wage — conservative); only states whose wage rule ties federal and is kept at the federal level would fall back to $2.13.

- **Follow-up (2026-11-07):** Chicago alcohol_service (MCC 4-60-140/-143: under 21 conservative, under 18 absolute; trained 18-20 restaurant servers lawful); CA alcohol under 18 (BPC 25663/25667 via DLSE); WA under-16 cooking/baking/machinery bans (WAC 296-125-141) and alcohol under 18 (RCW 66.44.340/.350); TX hazard list = federal (§ 51.014). Tipped minimum wage added for NC, AZ, MD, MO, CO, NJ (2026 medium, 2027 high), WI, NY + NYC (from 2027-01-01), MI (2026, 2027); no-tip-credit notes: MN, AK, OR, NV; no rule with reason: VA (no fixed cash wage), PA and FL (amount not stated in the fetched text). GA and TN have no state minimum wage, so the federal $2.13 applies.

**In progress / next:** tipped_minimum_wage for the remaining states (OH, MA, IN, TN ok via federal, etc.); TX alcohol ages (statutes site JS-only). VT done 2026-11-07 (VT DOL WH-30). Not done — MS (Lexis-hosted code, no MDES page found), NM (DWS site blocks fetches; NMOneSource 403). Their notes still say minor limits are not researched (federal floor applies). Remaining DOL-drafted wage effective dates (OH portal is JS; NJ 2026). `minor_prohibited_roles` beyond HO 7: none encoded (only role tag in use is `powered_industrial_truck`; state lists in notes).

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
- `predictive_scheduling` (premium keys, SEMANTICS #17; `rate` = `premium_basis` rate: `regular_rate` | `scheduled_rate`). Per affected employee and shift, for a change made inside `notice_days` of the shift:
  - added hours / new shift / extension: `change_premium_hours` × rate (`change_premium_hours_under_24h` when notice < 24 h). If `prorate_added_under_1h`: `min(change_premium_hours, added_hours)` × rate.
  - moved (date/time changed, no loss of hours): `moved_premium_hours` × rate.
  - reduced / cancelled: if `reduced_fraction_notice_hours` is null, or notice < it: `reduced_hours_fraction` × hours not worked × rate; else `reduced_premium_hours` × rate.
  - `premium_flat_dollars` (when set) replaces the hourly amount; `grace_minutes`: changes shorter than this cost nothing (Seattle 15).
  - coverage: `applies_if_employees_over` counted per `employee_count_scope` (`global`); `min_covered_employees` (Chicago 50); `covered_wage_max_hourly` / `covered_salary_max_annual` (Chicago: employees paid above are not covered).
  - exemptions: `voluntary_additional_hours_exempt`, `consent_must_be_written`, `text_message_counts_as_written`, `coworker_coverage_exempt` (shift trades/coverage between employees), `exemption_note`; Seattle-style conditions: `exemption_requires_group_message` (offer must go to `exemption_min_recipients`+ employees at once, not one-on-one), `exemption_only_for_absent_coworker_hours` (only the hours the absent employee can't work; not open shifts), `exemption_message_must_state` (list of statements the message must contain).
  - more premium keys (2026-11-07): `moved_premium_per_attribute` (LA, Philadelphia: 1 h for EACH of date / time / location changed); `under_24h_tiers` (SF: list of `{max_changed_hours, premium_hours}`; first tier with changed hours ≤ max applies to any change with < 24 h notice, `null` max = no limit); `reduced_premium_hours_cap` (reduced premium = min(cap, fraction × hours)); `reduced_hours_measure` = `"scheduled_shift"` (Emeryville, Evanston: the cap compares against the shift's scheduled hours, i.e. min(4, scheduled hours) for any cut/cancel with < 24 h notice) — default is hours not worked; `post_deadline_grace_hours` (Philadelphia: changes within 24 h after the posting deadline are free); `min_local_employees` (Berkeley: 10+ in the city); `employee_count_scope` `"city"`/`"city_stores"` (SF, NYC).
  - more exemption keys: `exemption_recipients` (`"all_qualified"` Philadelphia, `"all_eligible"` Oregon); `exemption_individual_ok_if_on_shift` (Oregon: an on-shift employee may be asked one-on-one, i.e. extensions; off-shift needs a group message); `standby_list_first` (Oregon: exhaust the voluntary standby list first); `coworker_absence_exempt` + `mandatory_overtime_exempt` (SF: covering an absent/no-show coworker is exempt even without consent).
  - `exemption_applies_to` (all Fair Workweek rules): kinds of change the voluntary/absence exemption covers, from `call_in` (new shift) and `extension` (extra hours on a shift); `[]` = none. SF also has `coworker_absence_exempt_applies_to` = `["call_in", "extension"]` (L.E.C. § 42.4(e)(4): "Another Employee previously scheduled to work is unable to work due to illness, vacation, or employer-provided paid or unpaid time off" — no new-shift/extension distinction), `voluntary_requires_no_coercion` (SF Rule 6.1: pay is owed only when the employer "requires" the change; uncoerced volunteers owe nothing, no writing needed) and `under_24h_changed_hours` = `"added_or_subtracted_plus_moved"` (Rule 5.3).
  - prohibition model (NYC retail, `premium_basis: "none"`): `cancel_or_reduce_prohibited_within_notice`, `added_hours_require_written_consent`, `consent_record_must_include`, `consent_deadline_minutes_after_start` (15) — violations, not premiums.
  - `min_rest_between_shifts.consent_must_be_written` (Evanston).
  - sector thresholds (SEMANTICS #19): `food_applies_if_employees_over` / `food_min_locations` replace the general threshold when `Store.sector == food` (Chicago 249/30, Evanston 199/30, Berkeley 99); `food_full_service_min_locations` (Seattle full-service restaurants: 40).
  - older keys: `change_premium_hours_max`, `change_premium_window_days`, `changes_restricted_within_notice` + `on_call_prohibited` (NYC: prohibitions, no premium), `min_locations`.
- `min_rest_between_shifts`: `premium_applies_to: "shift"` = whole next shift at the premium (Chicago, LA); absent = only hours inside the rest window. `premium_flat_dollars` (Philadelphia $40, `premium_multiplier: null`).
- `minor_limits.max_days_week` (NY, FL, PA, MI, NJ, WA, MA, MO, WI: 6) and `minor_limits.max_avg_hours_day` (MI 16-17: 8) — informational; the validator does not check them yet.
- `minor_limits.latest_end_before_non_school_day` is also used by WA, MI, AZ, MA, TN, KY, CT, ME, RI, AR, WY (Fri/Sat nights).
- Age bands are not always 14-15 / 16-17: CT uses 14-14 and 15-15, LA and AR use 16-16 / 17-17. A band with only a school-week rule is listed in `tests/test_state_minors.py::SCHOOL_WEEK_ONLY`.
- A 0 cap means "may not work" (CT: 14-year-olds weekly 0 h; 15-year-olds 0 h on school days) — retail/restaurant only.
- `meal_break.earliest_start_minute_of_shift`, `meal_break.employee_optional` (ND), `rest_break.max_minutes_without_rest` (WA: 180), `daily_overtime.applies_if_rate_below_min_wage_multiple` (NV: 1.5).
- Minutes are minutes-from-midnight for times of day (420 = 7 a.m., 1140 = 7 p.m.).

**Shortcuts taken:**
- DOL-drafted states: `minimum_wage.effective` = DOL table date (2026-11-05), not the statutory date (fixed for NY, FL, IL, MI, VA). Minor-hour limits not yet researched for states not listed above (federal floor applies; their notes say so).
- Minor-specific meal/rest breaks (e.g. 30 min after 5 h in PA/OH/MI/IL/NC/VA/MD; 6 h in NJ/WI/TN) are in notes only — `meal_break` has no age scope.
- Validator convention Mon-Fri = school days makes Friday-night/day rules stricter than law in NY, FL, WA, TN, OH, NC, MN (noted per state). NJ 16-17 summer 10 h / 50 h allowance not encoded (year-round 8 h / 40 h enforced). TN source is TDLWD's page + required poster (statute is Lexis-hosted).
- Maryland retail shift breaks: DOL table does not say paid/unpaid; encoded rest=paid, meal=unpaid, flagged in notes.
- City aliases ("nyc", "new york city") are not mapped; the city key is `new york`.
- CA seventh-consecutive-day overtime is in `notes`, not params (no field for it).
- CA 16–17 school-week weekly cap: only the Lab. Code § 1391 48 h cap is encoded; Education Code permit limits not yet checked.
- Texas § 51.013 cited from TWC's official PDF copy of Chapter 51 (statutes site is a JS app that the fetcher can't read).

## Coverage (rule count per file × type; – = no rule; see each file's `notes` for "no such law")

| file | wOT | dOT | meal | rest | minor | minRole | clopen | predict | report | wage | tipW | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| federal | 1 | – | – | – | 2 | 7 | – | – | – | 1 | 1 | 7 |
| AK | 1 | 1 | – | – | 2 | – | – | – | – | 1 | – | 8 |
| AL | – | – | – | – | 3 | – | – | – | – | – | – | 7 |
| AR | 1 | – | – | – | 4 | – | – | – | – | 1 | – | 7 |
| AZ | – | – | – | – | 2 | – | – | – | – | 1 | 1 | 8 |
| CA | 1 | 1 | 2 | 1 | 4 | 1 | – | – | 1 | 1 | – | 8 |
| CO | 1 | 1 | 1 | 1 | 4 | – | – | – | – | 1 | 1 | 6 |
| CT | 1 | – | 1 | – | 6 | – | – | – | – | 1 | – | 6 |
| DC | 1 | – | – | – | 4 | – | – | – | – | 1 | – | 6 |
| DE | – | – | 1 | – | 2 | – | – | – | – | 1 | – | 6 |
| FL | – | – | – | – | 3 | – | – | – | – | 1 | – | 12 |
| GA | – | – | – | – | – | – | – | – | – | – | – | 8 |
| HI | 1 | – | – | – | 2 | – | – | – | – | 1 | – | 6 |
| IA | – | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| ID | – | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| IL | 1 | – | 2 | – | 2 | 2 | – | – | – | 1 | 1 | 11 |
| IN | 1 | – | – | – | – | – | – | – | – | 1 | – | 8 |
| KS | – | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| KY | 1 | – | – | 1 | 3 | – | – | – | – | 1 | – | 6 |
| LA | – | – | – | – | 4 | – | – | – | – | – | – | 8 |
| MA | 1 | – | 1 | – | 4 | – | – | – | – | 1 | – | 6 |
| MD | 1 | – | 1 | 1 | 2 | – | – | – | – | 1 | 1 | 7 |
| ME | 1 | – | 1 | – | 4 | – | – | – | – | 1 | – | 6 |
| MI | 1 | – | – | – | 4 | – | – | – | – | 2 | 2 | 8 |
| MN | 1 | – | – | – | 3 | – | – | – | – | 1 | – | 8 |
| MO | 1 | – | – | – | 2 | – | – | – | – | 1 | 1 | 8 |
| MS | – | – | – | – | – | – | – | – | – | – | – | 7 |
| MT | 1 | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| NC | 1 | – | – | – | 3 | – | – | – | – | 1 | 1 | 8 |
| ND | 1 | – | 1 | – | 2 | – | – | – | – | 1 | – | 5 |
| NE | – | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| NH | 1 | – | 1 | – | 4 | – | – | – | – | 1 | – | 5 |
| NJ | 1 | – | – | – | 4 | – | – | – | – | 2 | 2 | 11 |
| NM | 1 | – | – | – | – | – | – | – | – | 1 | – | 7 |
| NV | 1 | 1 | 1 | 1 | 3 | – | – | – | – | 1 | – | 4 |
| NY | 1 | – | 1 | – | 4 | – | – | – | – | 1 | 1 | 11 |
| OH | 1 | – | – | – | 3 | – | – | – | – | 1 | – | 9 |
| OK | – | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| OR | 1 | – | 1 | 1 | 4 | – | 1 | 1 | – | 1 | – | 16 |
| PA | 1 | – | – | – | 4 | – | – | – | – | 1 | – | 9 |
| RI | 1 | – | 2 | – | 3 | – | – | – | – | 1 | – | 7 |
| SC | – | – | – | – | – | – | – | – | – | – | – | 7 |
| SD | – | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| TN | – | – | 1 | – | 3 | – | – | – | – | – | – | 8 |
| TX | – | – | – | – | 2 | – | – | – | – | 1 | 1 | 7 |
| UT | – | – | – | – | 2 | – | – | – | – | 1 | – | 7 |
| VA | – | – | – | – | – | – | – | – | – | 2 | – | 9 |
| VT | 1 | – | – | – | 2 | – | – | – | – | 1 | – | 8 |
| WA | 1 | – | 1 | 1 | 4 | 2 | – | – | – | 1 | – | 8 |
| WI | 1 | – | – | – | 2 | – | – | – | – | 1 | 1 | 8 |
| WV | 1 | – | 1 | – | 2 | – | – | – | – | 1 | – | 6 |
| WY | – | – | – | – | 2 | – | – | – | – | – | – | 7 |
| ca-berkeley | – | – | – | – | – | – | 1 | 1 | – | 1 | – | 7 |
| ca-emeryville | – | – | – | – | – | – | 1 | 1 | – | 1 | – | 6 |
| ca-los-angeles | – | – | – | – | – | – | 1 | 1 | – | 1 | – | 9 |
| ca-san-francisco | – | – | – | – | – | – | – | 1 | – | 1 | – | 10 |
| il-chicago | – | – | – | – | – | 2 | 1 | 1 | – | 1 | 1 | 12 |
| il-evanston | – | – | – | – | – | – | 1 | 1 | – | – | – | 6 |
| ny-new-york | – | – | – | – | – | – | – | 1 | – | 1 | 1 | 10 |
| pa-philadelphia | – | – | – | – | – | – | 1 | 1 | – | – | – | 10 |
| tx-austin | – | – | – | – | – | – | – | – | – | – | – | 4 |
| wa-seattle | – | – | – | – | – | – | 1 | 1 | – | 1 | – | 11 |
