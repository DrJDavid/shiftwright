# per_slot_headcount: UKG/Kronos-style labor forecast

What it represents: the corporate labor forecast as most WFM tools export it, one row per job per
interval with the required headcount. Corporate already did the work of turning sales into people.

| File | Interval | Headers |
|---|---|---|
| `forecast_30min_{normal,holiday,promo,light_january}.csv` | 30 min, explicit end | Location, Business Date (ISO), Job, Labor Code, Interval Start, Interval End (24h), Required Staff |
| `forecast_15min_{normal,holiday}.csv` | 15 min, start + length | Location, Business Date (MM/DD/YYYY), Job, Interval Start (12h), Interval (min), Required Staff |

The 15-min files differ from the 30-min ones only for Cashier, which follows the transaction pace
inside each hour (22/25/28/25%), so some 15-min boundaries are off the 30-min grid.

**Importer support: works.** Every column maps by itself (`Job` → role, `Business Date` → day,
`Interval Start`/`End` → start/end, `Required Staff` → headcount; `Location`, `Labor Code`,
`Interval (min)` ignored). 1,100–1,250 rows merge into a few hundred blocks; the demand equals the
truth exactly; readiness green on the corporate roster.

In the UI: set the week and hours from `../week_variants.json` first (holiday: Thu closed, Fri
06:00–23:00, Sat 07:00–23:00), then drop the file as Workload forecast and Import.

- 15-min file: set the store to **15-minute slots** first. Imports exactly.
- 15-min file into a **30-minute** store: today each row becomes a 30-min block, so the blocks overlap
  and headcount is double-counted, with no warning. Spec 1b: aggregate to the slot by peak.
- Solves (20 s): normal 91.5% coverage, holiday 86.2% (Black Friday needs more than 40 people),
  validator passed both times.
