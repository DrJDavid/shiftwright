# WS7 status

_Updated Fri Nov 6, ~22:00 CT._

**Done (M1):**
- Three-pane shell at 1280×720: Chat (35%) · Main tabs (Schedule live; Coverage, Fix disabled) · Rulebook rail
  (readiness checklist + Build schedule; collapsible, auto-collapses after a build).
- API client (`src/api/client.ts`) for config, readiness, solve, latest schedule, chat SSE, card submit.
  SSE reader over `fetch` (`src/api/sse.ts`) since `EventSource` can't POST.
- Chat: streams `text`, renders `card` inline (locks to a summary after submit/skip), refetches config +
  readiness on `config`, activity line for `tool`, `error` shown inline. Unknown card types render a
  "not available yet, skip" frame instead of hanging the turn.
- Cards: `store_basics` (name, state/city, week start must be Monday, slot size, timezone, hours per day incl.
  closed days) and `payroll` (hours cap, optional dollar cap, overtime).
- Schedule tab: stats (hours used / cap bar, wage cost, coverage %, uncovered cost, validator badge with
  report popover), role legend, employee × day grid with role-colored segment bars and breaks as gaps,
  hover details, "Uncovered" footer row of gap blocks with hover details, stale-schedule warning,
  infeasible banner.
- Mock API (`src/mock/`): in-browser, returns real `Response`s (so the real client/parser run), scripted
  onboarding chat with the card pause/resume protocol, a greedy mock solver whose metrics are all
  computed from its own shifts. UI shows a "Mock API" pill whenever it's on.
- Tests (vitest, `npm test`): formatting, SSE parsing, mock solve metric consistency, chat pause/resume.
  `npm run build` and `npm run lint` clean.

**Switching to the real API:** open with `?api=live` (remembered in localStorage; `?api=mock` to go back), or
set `VITE_API_MODE=live`. Default is mock until WS6 lands — flip the default in `src/api/index.ts`.
On first load the app creates a store via `POST /api/stores` (template `bigbox_mid`, overridable with
`VITE_STORE_TEMPLATE`) and remembers its id.

**In progress / next (M2):** remaining cards, rulebook rule list, coverage heatmap, gap explanations,
CSV drop → `csv_import`.

**Blocked on:** nothing. Need WS6 to verify against the live API.

**Shortcuts taken / notes for the coordinator:**
- Hand-typed only the API.md shapes absent from `contracts.ts`: chat/SSE events, `ChatMessage`, card
  props/results for the two cards, `Readiness`, `ImportPreview`, `OutreachState`, request bodies
  (`src/api/protocol.ts`).
- Raised `tsconfig.app.json` target/lib to ES2022 (for `Array.at`); eslint now ignores generated
  `src/contracts.ts` (its `eslint-disable` header triggered an unused-directive warning).
- Added dev dep `vitest` and `npm test` script (apps/web only).
- Mock fixture names/wages/demand are invented placeholders, used only in mock mode and labeled as such.
- Questions for WS6: (1) `/chat/card` is assumed to return 200 immediately while the original SSE stream
  resumes; (2) `GET /schedule` 404 when none exists is treated as "no schedule yet".
