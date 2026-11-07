# WS7 status

_Updated Sat Nov 7, slice 5. Rebased on main d73494b (contracts/API v1.4, real fix_day)._day not yet)._

## How David runs it locally

From the repo root, after `make install` once: `make dev`, then open **http://localhost:5173/?demo**
(`?demo=chicago|seattle|sf` once WS6 ships those templates). `make dev-api` now loads `.env` itself.

In the app: **Store ▾** (top right) lists the demo stores the server has (`GET /api/templates`: Austin, Chicago, Seattle, SF) or starts an empty one. Click **Build schedule**
(about 20–30 s), then use the tabs. Without an API: `cd apps/web && npm run dev`, open http://localhost:5173/?api=mock&demo.

## Running it (details)

- Live API (default now): start the API, then `API_PORT=8017 npm run dev -- --port 5177` (proxy port defaults to 8000).
- `?api=mock` switches to the in-browser mock (remembered in localStorage; `?api=live` to go back; `VITE_API_MODE=mock` for a mock default).
- Demo key: `?key=...` (remembered in localStorage, then removed from the address bar) or `VITE_DEMO_KEY`. Sent as
  `X-Demo-Key` on every request, including the chat SSE and CSV upload.
- `?gallery` (dev server only): every card with sample props from the WS4 demo fixture, for visual QA.
- On first load the app creates a store (`POST /api/stores`, template `bigbox_mid`, `VITE_STORE_TEMPLATE` to override) and
  remembers its id per mode (`sw.storeId.live` / `sw.storeId.mock`). Clear that key for a fresh store.

## Done

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
