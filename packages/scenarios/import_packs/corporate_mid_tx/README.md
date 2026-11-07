# corporate_mid_tx: big-box corporate export style

40 team members, Store T2290 Katy TX. Workday/Kronos-flavoured exports, different from the demo store's:
zero-padded string IDs (`0048100`), `Legal Name`, `Home Org` (UPPERCASE org names), `Job Profile`,
`Emp Type` (`Full-Time` / `Part-Time` / `Seasonal`), `Pay Rate` (`$24.25`), `Std Hrs`, `Min Hrs/Wk`,
`Max Hrs/Wk`, US dates for DOB and ISO for hire date. Seven departments (Leadership, Front End, Guest
Service, Softlines, Hardlines, Fulfillment, Flow), eight roles, **truck Tue/Thu/Sat 04:00–10:00** (4 on
Truck Unload). Forecast is one row per 30-minute interval in 24h time with `Req FTE` as `2.0`.

| File | Rows | Headers |
|---|---|---|
| roster.csv | 40 | Employee ID, Legal Name, Home Org, Job Profile, Emp Type, Pay Rate, Std Hrs, Min Hrs/Wk, Max Hrs/Wk, Date of Birth, Hire Date, Mobile Phone, Location |
| training.csv | 84 | Employee ID, Skill Name, Completed On |
| availability.csv | 40 | Employee ID, Legal Name, Monday..Sunday (`ANY`, `OFF`, `04:00-13:00`, `16:00-22:00`), Last Updated |
| forecast.csv | 1184 | Business Date (ISO), Org Path, Job, Interval Start, Interval End, Req FTE |
| history.csv | 642 | Employee ID, Work Date, Job, Punch In, Punch Out (four past weeks, 12h) |

## In the UI
1. Empty template, TX. Open 08:00–22:00 daily, 30-min slots, **staff may start 4 h before open**
   (pre-open 240 min) or the 4 am truck can't be covered; truck days Tue/Thu/Sat.
2. Roster: **`Home Org` is not mapped automatically**: the card says "Still needed: home department".
   Map `Home Org` → home department by hand. Everything else maps (`Legal Name` → name, `Pay Rate` →
   wage, `Mobile Phone` → phone, `Min/Max Hrs/Wk` → min/max hours; `Std Hrs`, `Job Profile`,
   `Location` ignored).
3. Training, availability, forecast: map by themselves. The forecast's 1,184 interval rows merge into 94
   blocks.
4. History: **`Punch In` is not mapped** (while `Punch Out` → end is). Map `Punch In` → start by hand.
5. Payroll 900 h. Priorities: Leader on Duty 200, Guest Service 40, Truck Unload 35, Cashier 30,
   Drive Up 25, Order Pick 25, Softlines 20, Hardlines 20.
6. Readiness green; build: about 94% coverage, validator passes (remaining gaps are mostly
   availability: Softlines/Hardlines mornings, some LOD hours).
