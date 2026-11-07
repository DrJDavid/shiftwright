# WS7 status

_Updated Sat Nov 7, Lane B (PUNCHLIST B1–B4: routes, accounts, create workplace, switcher, guided setup), branch
`cursor/B1-web-shell` off main 9413f5e. Built against the PUNCHLIST A1 endpoint table; A1 isn't on main yet._

## How David runs it locally

From the repo root, after `make install` once: `make dev`, then open **http://localhost:5173/**. Sign up (or sign
in), then **New workplace** (name, kind of business, city/state) or **Or explore a sample workplace**. In a
workplace, **My workplaces ▾** (top right) switches workplaces, makes a new one, opens a sample, or signs out.
Click **Build schedule** (about 20–30 s), then use the tabs.

Without an API: `cd apps/web && npm run dev`, open http://localhost:5173/?api=mock. The mock keeps accounts and
workplaces in memory, so a page reload signs you out (sign up again; any email + 8-character password).

## Routes (B1)

| Path | Page | Signed out |
|---|---|---|
| `/` | Landing: headline, three proof points, Get started / Sign in | shown |
| `/signup`, `/login` | Forms with inline errors (409 → "already exists" on the email field, 401 → "Wrong email or password.") | shown; signed in → `/workplaces` |
| `/workplaces` | My workplaces (sample copies listed separately under "Explore a sample") | → `/login` |
| `/workplaces/new` | Create a workplace (B2); signup lands here | → `/login` |
| `/w/:id` | The workspace (old `App.tsx`, now `src/Workspace.tsx`); 404 → "Workplace not found" | → `/login`, then back here |

- Session check: `GET /api/auth/me` once on load (`src/auth/AuthProvider.tsx`). Any later 401 from the API (expired
  session) signs the page out and sends you to `/login` with a return path; **Sign out** goes to `/login` without one.
- Live fetches use `credentials: 'include'` (cookie `sw_session`). The FastAPI static handler already falls back to
  `index.html`, so deep links like `/w/<id>` work in production.
- The auto-create-a-store bootstrap and `?demo` are gone; nothing is created until you ask. `sw.storeId.<mode>` is still
  written when a workplace opens (the phone view `?employee=` falls back to it).
- Production builds are always live (unless built with `VITE_API_MODE=mock`): no "Mock API" pill, no `?api=mock` hints,
  and the mock + fixtures are tree-shaken out (main chunk 2.6 MB → 467 kB). `npm run dev` keeps `?api=mock|live`.

## Guided setup (B4)

- `/w/:id` is in **setup mode** until `GET /schedule` returns a schedule: a step tracker on the left and the chat
  centered (max 3xl). No tabs. Once a schedule exists (Build, or the agent's own solve via `onScheduleChanged`) it
  switches to **workspace mode**; the chat becomes the **Ask Shiftwright** drawer. The `ChatPane` keeps its place in
  the tree, so the conversation survives the switch (tested).
- Steps (`src/lib/setupSteps.ts`, tested) use the check ids from `apps/api/.../readiness.py`:
  Business = `store_basics`, `jurisdiction`, `business_type`; Hours & budget = `budget`; Team = `roles`, `employees`,
  `training`, `equipment_roles`, `minors_on_tagged_roles`, `minimum_wage`; Staffing = `demand`, `priorities`,
  `roles_without_demand`, `staffing_draft`; Rules = `provisional_rules` (+ any id the map doesn't know). A step is
  done when all its checks are `ok`; `severity: warn` shows "!" (attention). Hover/focus shows each check's detail;
  the current step shows its first open detail inline. Team carries the Is equipment / Not equipment buttons.
- **Build my schedule** is enabled when `ready`; otherwise it's disabled with "Build anyway" and a one-line warning.
- The mock's readiness now emits the same ids (it used `law_pack` for `jurisdiction`) with `severity`.

## Assumptions about the backend (Lane A)

- Exactly the A1 table: `POST /api/auth/signup {email,password,name}` → `{user}`; `POST /api/auth/login` → `{user}`, 401
  on bad credentials; `POST /api/auth/logout` → 204; `GET /api/auth/me` → `{user}` or 401; `GET /api/workplaces` →
  `{workplaces:[{id,name,sector,city,state,updated_at,has_schedule}]}`; `POST /api/workplaces/sample {template}` →
  `StoreConfig` named "Sample: …".
- Samples are recognised by the "Sample: " name prefix (to list them under "Explore a sample").
- `POST /api/stores` (template `empty`) is sent `name, sector, business_description` (omitted when blank) and
  `jurisdiction {state, city}` (city lower-cased, as before). Until A2 lands the server may ignore `sector` /
  `business_description`.
- `/api/workplaces/sample` 404/422 → "isn't on this server yet" and the template is hidden for the session.
- Errors: string `detail` is shown as-is; FastAPI validation arrays get a generic message.
- Client-side password minimum is 8, matching A1.

## Mock API (accounts)

`src/mock/server.ts`: users + one session (one browser = one cookie jar); signup 422/409, login 401, logout 204, me
401; stores remember their owner and someone else's store is a 404; `/workplaces` lists mine; `/workplaces/sample`
copies the Austin fixture (`demo`/`tiny` only) as "Sample: …". Stores created without a session (older tests) stay open.

## Tests

`src/App.test.tsx` (jsdom + Testing Library, MemoryRouter over the mock): signed-out redirect to `/login` from
`/workplaces`, `/workplaces/new`, `/w/:id`; landing creates no store; signup inline errors → `/workplaces/new`; taken
email; wrong password; create-workplace required fields; create posts `{template: empty, name, sector, business_description,
jurisdiction}` and opens `/w/:id` with the switcher listing it checked; explore a sample. `src/mock/mock.test.ts`: mock
accounts + ownership. 40 tests total; `npm run build`, `npm run lint`, `npm test` clean.

## Next (Lane B)

- B4 guided setup, B5 workspace tabs/header, B6 plain-language pass (PUNCHLIST).
- Wire-up check against the real A1 once it lands (cookie on the chat SSE + CSV upload, 401 handling).

## Running it (details)

- Live API (default): start the API, then `API_PORT=8017 npm run dev -- --port 5177` (proxy port defaults to 8000).
- Dev server only: `?api=mock` switches to the in-browser mock (remembered in localStorage; `?api=live` to go back;
  `VITE_API_MODE=mock` for a mock default).
- Demo key: `?key=...` (remembered in localStorage, then removed from the address bar) or `VITE_DEMO_KEY`. Sent as
  `X-Demo-Key` on every request, including the chat SSE and CSV upload. (A1 removes DEMO_KEY when auth is on.)
- `?gallery` (dev server only): every card with sample props from the WS4 demo fixture, for visual QA.

## Done

**Slice 8 (demo moments)**
- Minor protection made visible (`src/lib/minors.ts`, tested): for every employee inside a law pack
  `minor_prohibited_roles` rule's age band (`age_min ≤ age < age_below`, sector per #19) who is trained on a role
  carrying one of its `role_tags`, the receipt's **Minors kept off hazardous roles** section says e.g. "Blake Allen,
  15 — trained: Line Cook (Cooking, Fryer) — scheduled only as Server; barred by US.minor_prohibited_roles.7 (29 CFR
  § 570.33(e)-(h) …)" with the citation link; if they were scheduled in a barred role it says so in red. The
  Schedule grid shows a shield on those minors' rows with the same line on hover.
- Fix tab leads with **day-level coverage** (`src/lib/dayCoverage.ts`, tested; SEMANTICS #1 restricted to the
  day, per 5-minute step from demand and role segments): before the call-outs → after → plan if the first choices
  say yes / if nobody does; the outreach panel's headline is the live day figure; weekly numbers are secondary text.
  Austin Saturday: 91.7% → 80.6% → 89.3% best / 87.4% worst, filled to 90.9%.

**Slice 7 (final pass)**
- Blank store: hours start open every day (9a–9p, labelled a starting guess) with "Same hours every day … Apply to
  open days" and "Closed on: Mon … Sun" toggles; the clipped per-row Closed checkbox is gone.
- Harbor Grill #12 (template `demo_restaurant`) appears in Store ▾ from `/api/templates`; `?demo=restaurant` too.
  The Fix tab prefills its scenario (Saturday 3:30p, e005 Lane Flores + e028 Noel Garcia) for food stores.
- Fix tab: refreshes the schedule right after `/outreach/start` (call-outs removed, actions applied, per WS6) and
  offers "Just make today's changes, don't text anyone" (`POST /fix/apply`; mock supports it too).
- Receipt: rules nothing in the schedule triggers (no tagged roles, nobody in the age band, not applicable this week)
  are one-liners under "Also checked"; Harbor Grill went from 6 to 4 pages, Austin 3, Chicago 4.
- Engine "why" text humanized in the grid tooltip and Fix tab; tipped roles marked "(tipped)" in the legend.
- Final 1280×720 pass, live API + real engine, beats build → receipt → call-outs → texts → phone:
  Austin, Chicago and Harbor Grill each build in ~18 s, fix in <2 s, fill by text; after outreach the badge is
  "0 hard violations ✓" in all three (WS6's fix works) and called-out shifts are gone from the saved schedule.

**Slice 6 (contracts v1.5: any business)**
- `store_basics`: "What kind of business is this?" (`sector`) and "In a few words" (`business_description`) first;
  "Split shifts allowed" → `max_shifts_per_day` 2/1; summary shows the business type.
- Store ▾ "Start from scratch": business name + state + city → template `empty` (no retail roles), so a taqueria
  starts clean; the old big-box default is "Start a big-box store".
- `department_staffing`: busy-time day choices = the server's `day_groups` plus Every day and each single day; any
  v1.5 `day_group` (all / weekday / weekend / saturday / sunday / mon…sun / comma lists) is labelled and applied
  per day in the preview (`src/lib/vocab.ts` `dayGroupDays`, tested); `rationale` shown per role ("Suggested
  because: …"); copy says suggestions are guesses; Tipped badge on tipped roles.
- `coverage_grid` `day_type: "custom"`: titled by its `days`.
- Events: `Event.label` input and display everywhere (`eventName`), kinds ordered by `Store.sector`.
- Tipped pay (SEMANTICS #20): Tipped badge on roles (Store tab, staffing card); People table shows the tipped cash
  wage; shift tooltip prices tipped shifts at the tipped wage; receipt checks `tipped_minimum_wage` from its params.
- ROLE_TAGS chips with friendly names (Forklift / powered truck, Fryer, Meat slicer, …) on roles in the Store tab and
  on hazardous-job law lines in the rulebook (with the store roles carrying each tag); receipt honours `age_min`.
- `estimate` demand: amber dashed cells + note in the Store tab Demand view.
- Split shifts: all of a day's shifts on one track (two bars) with "11a–2p, 5p–9p" (render test); Store tab shows
  the split-shift policy and the business type.
- Chat stays usable while an agent card is open: sending cancels the card (API v1.2 supersede) and starts a new turn.
- Re-checked Austin + Chicago beats at 1280×720 (build ~19 s, fix ~1.8 s, texts fill in ~40 s), plus a cold start
  for "La Esquina, Chicago" (blank store → agent opens store basics with the business question).
- Tests: 26.

**Slice 5 (v1.4 + real fix_day + demo polish)**
- Store ▾ from `GET /api/templates` (falls back to the built-in list on older servers / the mock).
- Import card: "Still needed" from `required_any_of` (the old client-side copy stays only as a fallback); after
  commit, `X-Import-Warning-Count` → `GET /import/{kind}/warnings`, shown as "N things to check" on the locked card.
- Readiness rail: auto-tagged powered-equipment roles get "Is equipment" / "Not equipment" buttons
  (`POST /equipment_roles`). Role names are read from the check's detail text (no structured list in the API).
- Fix tab on the real engine: direct changes (extend/call-in) listed with premium chips; role moves and "still
  uncovered" stretches folded into two expandable lines (Chicago's plan has ~45 actions); ids and 24-hour times in
  engine prose shown as names and 12-hour times (`src/lib/humanize.ts`, display only); candidate table shows
  `premium_pay_dollars` / `law_rule_ids` / `premium_note` ("No premium · Voluntary call-in accepted in writing" or
  "+$20.75 Chicago predictability pay"), the shift's `why` headline, and the candidate `why`; a banner states the
  outreach mode (one at a time / group offer, round N) and `OutreachState.premium` (owed / exempt / not applicable +
  note, legal source text folded). Group offers get one row of reply buttons per `waiting_employee_ids`.
- After each accept the Schedule reloads `GET /schedule` (the API now saves a validator report with it).
- Compliance receipt: "Call-out repairs" section with each accepted call-in's premium from `premium.by_employee`.
- Called-out shifts are struck through in the Schedule grid ("called out") once reported in the Fix tab.
- The chat column folds away when opening Fix / Store / Receipt (one click to reopen).
- Bug fix: `?demo=<city>` sometimes created an *empty* store (React StrictMode ran the load effect twice; the
  second run no longer saw `?demo`). The initial load now runs once.
- Demo beats checked at 1280×720, live API + real engine, Austin and Chicago: build ~18–19 s (overlay), fix plan
  ~1.5 s, scripted texts fill in ~40 s, phone view, receipt prints.

**Slice 4 (Sat 03:15)**
- CSV import card: dropdowns from `ImportPreview.target_fields`; "Still needed" computed from `required_fields` plus the
  server's alternatives (birth date satisfies age, first + last satisfies name, any avail_* column) — mirrors
  `imports.unmapped_required`; the old card never cleared and kept Import disabled.
- `department_staffing` card (API.md v1.3): one card per department; each role has "Most of the day", busy times
  (headcount, Weekdays/Saturday/Sunday, from–to; add/remove), opening crew (n, minutes before open) and closing crew
  (n, minutes after close); prefilled from `suggested` with a "Suggested" tag or "Use suggestion" per role and
  "Looks right" for the whole department; live **Preview** heatmap per day group computed client-side by
  `src/lib/staffing.ts` (base over open hours, peaks replace base, crews outside open hours; unit-tested);
  collapses to "Front of Store: 1–2 Guest Service Desk, 1–5 Cashier, …". `coverage_grid` renders read-only when
  `readonly: true`. In the gallery and in the mock onboarding (after payroll; suggestions read from the fixture demand).
- Store ▾ localities: Austin (`demo`), Chicago (`demo_chicago`), Seattle (`demo_seattle`), SF (`demo_sf`). A locality
  whose template the server rejects (404/422) is hidden for the session with a note. `?demo=<city>` works too.
  Older API without `demo`: falls back to PUTting the bundled fixture.
- Schedule grid: `Shift.why` headline in the hover tooltip ("click for N more"), all items in a click popover; nothing
  shown when empty. The mock fills `why` with facts about its own greedy choice.
- Fix tab: per action, "+$17.50 Chicago predictability pay" (amount from `premium_pay_dollars`, label from the law
  rule in `law_rule_ids`, link to its source), or "No premium · <rule> checked", or "No predictive-scheduling law in
  this location's law pack". Rationale shown as written. Mock computes premiums only from an embedded law pack's
  `predictive_scheduling` params (threshold, `change_premium_hours`, `voluntary_additional_hours_exempt`), per #17.
- **Compliance receipt** tab: store, week, jurisdiction, law-pack coverage; validator verdict; solver-reported vs
  validator-recomputed metrics side by side (differences highlighted); every law rule with summary, citation title +
  URL, excerpt, last verified/confidence, and how the schedule meets it from the rule's own params
  (`src/lib/compliance.ts`: OT hours and max weekly hours, longest day, shifts over the break trigger and how many
  have the break, minors' ages/longest day/week/earliest start/latest end vs limits, under-18 shifts in tagged roles,
  shortest rest, lowest wage vs minimum, predictive-scheduling applicability by employer size) plus the validator's
  violations for that rule; rules not applicable this week say why (school week, employer size); store rules with
  hard Met/violations and soft cost this week; premium pay + overtime. **Print / Save PDF** prints only the receipt
  (portal + print CSS) — the Austin demo prints on 2 Letter pages. "Run the validator" (`POST /validate`) if missing.
- **Employee phone view** `?employee=<id>&store=<id>` (390×844): their week (times, roles, breaks, total hours), an
  open shift offer with Accept / Decline (through `POST /api/sms/mock-reply`, only when the messenger is mock;
  otherwise "Reply YES or NO to the text"), "Saying no is fine", message history. No badges, nags or upsell. Fix tab
  thread: "Open <name>'s phone" shows it in an inline phone frame (works with the in-browser mock too) and, in live
  mode, a new-window link.
- Import commit-time warnings: not exposed by the API yet (stored server-side only), so nothing to show.
- Tests: 21. build, lint clean.

**Slice 3 (Sat 01:45)**
- Real engine checked on the demo store (174 shifts, 69 gaps, 90% coverage, validator 0 hard): grid, stats, heatmap and
  gap panel render correctly with real data. Fixes: heatmap now fits the pane width (it overflowed at 4a–11p); schedule
  rows grouped by home department with per-department totals (toggle "Group by: Dept / Hours"); 14 distinct role
  colors (was 9 with repeats); a day's "$X gaps" header jumps to that day in the Coverage tab.
- Solve progress overlay with elapsed seconds and a time-based bar (labelled as an estimate; typical 20–30 s).
- Demo store loader: `?demo` or Store ▾ → "Load the demo store" creates a store and PUTs
  `packages/scenarios/fixtures/demo_store.json` (bundled read-only via `src/lib/demoStore.ts`).
- **Store tab** (read-only review): People (sortable, searchable: name, department, age with Minor badge, status, wage,
  hours range, trained roles by name, extra-shift record from attendance, tenure), Roles (by department, gap $/h, min
  age, role tags, trained count), Training matrix (grouped by department, totals row), Demand (role × slot heatmap
  per day with store-open band and trucks/events marked, staff-hours per day), Availability (week strip + lines;
  Mon–Fri ranges collapsed), Budget & rules (caps, OT, approvals, demand total vs cap, constraints, store hours,
  link to the rulebook). The chat column can be hidden (Hide / "Chat" strip) to give the tables room.
- **Fix call-outs tab** (M3): pick the day, the time now, and who called out (chips of that day's shifts; prefilled
  with the demo Sat 6:04a e034/e052/e053 when those people work that day) → `POST /fix` → coverage now / best / worst,
  plan actions (lever, person, role, time, cost, rationale, law ids), ranked outreach queue (shift offered, cost,
  likely-yes %, why, live status chips) → **Start texting** → phone-style thread from `GET /outreach/stream`
  (falls back to polling `GET /outreach` every 2 s), simulated Yes / No / Question replies (`POST /api/sms/mock-reply`),
  Stop texting (`/outreach/cancel`), coverage number animates and the Schedule tab updates (badge "Not validated",
  matching the API, which saves outreach schedules without a validation). The tab stays mounted, so outreach survives
  tab switches. `503` from `/fix` shows "The call-out fixer isn't on this server yet" with a `?api=mock` link.
- Mock API: `src/mock/fix.ts` fake FixPlan + outreach loop with WS6-style scripted replies (rank 1 declines, next
  asks a question then accepts, 4 s apart; manual replies win), `/outreach/stream` SSE, `/sms/mock-reply`.
  Mock metrics come from `mockScore` (factored out of the mock solver), never typed in.
- Chat handles token-streamed `text` (leading blank line of a later step is trimmed when it starts a new bubble).
- Tests: 16 (adds mock fix/outreach). build, lint clean.

**M1** — three panes at 1280×720, schedule grid from `/solve`, chat over SSE with cards, readiness rail, mock API.

**Live API verified** (scripted + headless Chrome against apps/api on 8017, live LLM, ~3 short turns):
create store → onboarding chat (`tool`/`text`/`card`/`config`/`done` events, card pause/resume via `/chat/card`) →
drop `roster.csv` on the chat → preview + mapping → commit → agent picks up and opens `payroll` → readiness updates →
solve → grid, stats, validator badge + report. (Solve runs WS6's engine stub until WS1 lands: no shifts, all demand as gaps.)

**v1.1**
- Breaks are cut out of shift bars at minute precision (5-minute off-grid breaks render exactly); segments already used minutes.
- `GET /schedule` may return `validation: null` → badge says "Not validated".
- `coverage_grid` card uses `days` + `start_minute`; `store_basics` card has School week (unknown / yes / no → `school_week`).
- X-Demo-Key support (above).

**M2**
- Rulebook rail: readiness meter (checklist auto-collapses once ready, click the meter to toggle) + rule list grouped
  Law · Corporate · Store rules · Employee preferences · Not modeled. Law lines come from `GET /laws/resolve` (or
  `config.law_pack` when embedded): Hard/Pay badge, level chip, expand for citation link, excerpt, last-checked date and
  an "not yet verified" note. Constraints show note (or a description built only from their own params), Hard/Soft,
  $ weight, source chip; provisional rules are dimmed with Confirm / Reject (full-config PUT on a fresh GET).
- Gap explanations: click any red block (Schedule "Uncovered" row or Coverage heatmap) → side sheet with
  `POST /gaps/explain` text plus reasons grouped by code, employee names, law-rule summary + citation link, rule note.
- Coverage tab: per-day role × slot heatmap. Required = store demand, scheduled = role segments, red = the solver's
  own `gaps` (nothing recomputed). Hover for need/scheduled/gap; day picker shows each day's gap cost.
- All cards: `roles`, `training_matrix`, `coverage_grid` (paint with a 0–5 brush), `events`, `csv_import` (upload →
  mapping table → commit via `/import/{kind}[/commit]`), `propose_rule` (Always / Usually + $ / Not a rule), `tradeoff`,
  `conflict_menu`, `employee_availability`, plus M1's `store_basics` and `payroll`.
- CSV drop anywhere on the chat opens a local `csv_import` card (kind guessed from the file name, changeable). It is not
  an agent card, so nothing is POSTed to `/chat/card`; after commit the web sends "I imported X (N rows)." so the agent continues.
- Stats bar fits at 1280 with the rail open; day headers use compact money ($8.8k).
- Tests: 14 (vitest). `npm run build`, `npm run lint`, `npm test` clean.

## Next

- Re-check the Fix tab against the real `fix_day` + WS6 scripted messenger when they land (FixPlan field use,
  `why` text length, system notes in the thread). Call-in shifts aren't visually marked in the Schedule grid yet.
- FixPlan coverage numbers are whatever the engine reports (likely week-level, so a 3-person Saturday change moves
  it only a little); a day-level number would need to come from the engine.
- `conflict_menu` shows raw constraint/law ids under "Involved"; could map to rule notes.
- Coverage heatmap: cells are slot-sized; a gap shorter than a slot still marks the whole cell red (hover shows the exact range).

## Remaining demo issues

Final pass (slice 7):
1. **WS1/WS2, visible in the Harbor Grill demo:** right after **Build schedule** the validator reports 2 hard
   `metrics_mismatch` (engine `total_wage_cost` $16,050.40 vs validator $14,259.50; objective likewise). The engine
   and validator price tipped hours differently (SEMANTICS #20). After the call-out fix the saved schedule is
   re-validated and shows 0 hard, but a receipt printed right after the build says "Did not pass".
2. The Harbor Grill receipt says the Chicago tipped minimum, fryer/cooking and alcohol rules have no violations, but
   with no 14–15-year-olds scheduled the fryer rule is listed under "Also checked" (true, but the demo story wants a
   15-year-old trained on the fryer — WS4's fixture doesn't schedule one this week).
3. (Fixed in slice 8: the Fix tab now shows the day's coverage.)

Earlier notes:

Still open after slice 6 (WS6 is on 1–3): the badge shows "1 hard violation" after outreach (metrics_mismatch on
soft-rule cost); called-out shifts stay in the saved schedule; extension actions aren't applied. New: a store
with every day closed needs each "Closed" box unticked in store basics (no "open every day" shortcut).

## Remaining demo issues (slice 5)

1. **WS6/WS1:** after outreach, the called-out employees' original shifts are still in the saved schedule
   (e034/e052/e053 still on Saturday in Austin). The web strikes them through, but the employee view and the counts
   still include them.
2. **WS6:** after outreach the saved validator report flags `metrics_mismatch` (claimed `soft_penalty_dollars` 2985 vs
   recomputed 2945), so the badge turns to "1 hard violation" right after a successful fix. The committed schedule's
   metrics should be the recomputed ones before validating.
3. **WS1/WS6:** `FixAction.rationale` and `OutreachCandidate.why` use ids and 24-hour times (the web rewrites them for
   display); extension actions carry premiums but aren't applied to the schedule or counted on the receipt — unclear
   whether the leader is expected to apply them manually.
4. Chat input is disabled while a card is open; API v1.2 lets a new message supersede the card, but the web doesn't
   use that yet (would need to abort the paused stream).
5. Plan coverage numbers are week-level (Chicago 88.9% → 90.6%), so a Saturday rescue looks small. A day-level number
   would have to come from the engine.
6. Equipment-role buttons depend on the readiness detail wording; a structured `auto_tagged_role_ids` would be safer.

## API-side notes for WS6

Slice 4 (open):
- A way to list available store templates (e.g. `templates: string[]` in `/api/health` or `GET /api/templates`), so the
  Store menu can hide missing localities without trying to create a store.
- `ImportPreview`: the "alternatives" in `unmapped_required` (first+last for name, birth_date for age, any avail_*)
  aren't in `required_fields`, so the web mirrors them in `src/cards/csvKind.ts`. A `required_alternatives` field
  (e.g. `{name: [["first_name","last_name"]], age: [["birth_date"]]}`) would remove the copy.
- Compliance receipt can't show yet: premiums itemised by law rule and employee (only the weekly total exists);
  which law rules the validator actually evaluated (vs skipped); commit-time import warnings.

Earlier:

1. Readiness has no "wages ≥ minimum wage" check yet (API.md v1.1 lists it). The web renders whatever checks arrive.
2. Readiness details show raw ids: "Nobody trained for: guest_service_desk, …" and "No demand on day(s): 0, 1, …".
   Role names and weekday names would read better on the projector.
3. `/gaps/explain` text uses 24-hour times ("10:00–22:00") and cents; the brief asks for "6:30a" style. The web shows its
   own 12-hour header above the text, so this only affects the paragraph.
4. `ImportPreview` doesn't list the target fields, so the web mirrors `imports.TARGETS` keys for the mapping dropdowns
   (`src/cards/CsvImportCard.tsx`). A `target_fields` (with required flags) in the preview would remove the copy;
   that needs a contracts request since `ImportPreview` is in API.md.
5. The engine stub reports `soft_penalty_dollars: 0`, so the validator flags `metrics_mismatch` (2 hard). Goes away with WS1.
6. To verify: if the browser disconnects while a card is pending, does the turn lock release, or does the store get 409 on
   the next chat until `card_timeout_s` (30 min)? Not tested.

## Notes for the coordinator

- Hand-typed only API.md shapes absent from `contracts.ts` (`src/api/protocol.ts`): SSE events, `ChatMessage`, card
  props/results for all 11 cards, `Readiness`, `ImportPreview`, `OutreachState`, request bodies.
- `vite.config.ts` reads `API_PORT` via `loadEnv`; `server.fs.allow` includes `../../packages/scenarios/fixtures` (mock + gallery).
- No new deps.
