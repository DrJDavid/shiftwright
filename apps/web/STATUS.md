# WS7 status

_Updated Sat Nov 7, ~01:45 CT. Rebased on main 4f53a85 (real engine solve_week; fix_day not yet)._

## How David runs it locally

From the repo root, after `make install` once:

```
set -a; . ./.env; set +a; make dev
```

then open **http://localhost:5173/?demo** (the `?demo` loads a fresh copy of the demo store, Store #0417 with
60 people; afterwards plain http://localhost:5173 reopens the same store). `make dev` runs the API on :8000 and Vite
on :5173 (Vite proxies `/api` to :8000). The `set -a; . ./.env` part matters: `make dev-api` doesn't read `.env`
itself, so without it the chat has no OpenRouter key. **Suggested Makefile fix (coordinator, root file):**
`dev-api: set -a; [ -f .env ] && . ./.env; set +a; uv run uvicorn shiftwright_api.main:app --reload --port 8000`.

In the app: **Store ▾** (top right) loads the demo store or starts an empty one at any time. Click **Build schedule**
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

## API-side notes for WS6

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
