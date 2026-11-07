# Punch list: from demo to product (Sat Nov 7, night shift)

*Written 03:50 CT by the Claude Code coordinator. Freeze 13:00, demo 16:00.*
*Goal: a judge watches David **sign up, create a workplace from scratch, set it up in chat, build the
week, and handle call-outs** on the deployed URL, and it feels like a product, not a dev console.*

## Branch and merge rules (updated 05:25, these override anything below)

- **Exactly one merger: the Cursor coordinator.** It is the only agent that commits to `main`, merges, and
  pushes. Workers (Cursor task agents **and** the Claude Code session) commit only on their own branch,
  never on `main`, and never push.
- Workers: branch `cursor/<task-id>` (Claude Code uses `claude/<task-id>`) cut from the **current** `main`;
  rebase onto `main` before reporting; finish with `READY TO MERGE: <branch> <commit> — <what>`.
- Coordinator, before each merge: trial-merge in a scratch worktree, `uv lock && uv sync && uv run pytest`
  plus `cd apps/web && npm run build && npm run lint && npm test`; merge with `--no-ff` only when green;
  push `main`; tell the other workers to rebase. Never force-push. Update the status board below.
- No one edits files in the main checkout's working tree except the coordinator.

## Status board (05:25)

| Task | State |
|---|---|
| C1 fix-plan G1–G3, C2 split shifts, D1 minor hazard rules, E1 food exports | **merged** |
| Plain-language role priorities, chat setup fixes (Claude Code) | **merged** (`7304274`, `80e21fc`) |
| A1 auth, A3 generated businesses, B1 web shell, E2 rescore, E4 dataset builder | on branches, need rebase onto `main` + review |
| A2, B2–B7, C3, E3 | not started |

## How to run these with Cursor

- **One task per agent, one branch per task:** `cursor/<task-id>` (e.g. `cursor/A1-auth`), cut from `main`.
- Every agent reads `AGENTS.md` first, then its task below. Stay inside the task's **Files**. Never edit
  `contracts/` (except where a task says so), the engine/validator outside your lane, or `.env`.
- Tests first where the task lists them. Before reporting: `uv run pytest` (Python) and/or
  `cd apps/web && npm run build && npm run lint && npm test` (web) must pass.
- **Don't push, don't merge.** Finish with `READY TO MERGE: <branch> <commit> — <what>`. The coordinator
  (Claude Code) trial-merges, runs everything, merges to `main`, and pushes.
- Lanes A–E touch disjoint folders, so they can run in parallel. Inside a lane, run tasks in order.
- No paid LLM calls from agents' code or tests. Live-agent tests stay skipped without a key.

---

## Lane 0: humans (David), do these first (~10 min)

- [ ] **0.1 Persistent storage on Railway.** The Dockerfile already points SQLite at `/data/shiftwright.db`;
      the service just has no volume, so every deploy wipes all data. Dashboard: project **modest-spirit** →
      service → **Settings → Volumes → Add volume**, mount path `/data`. (CLI: `railway volume add --mount-path /data`.)
- [ ] **0.2 Fund OpenRouter with separate capped keys:** an *app* key (~$20 limit) and an *evals* key
      (~$25 limit). Never give coding agents a paid key.
- [ ] **0.3 Railway variables:** `OPENROUTER_API_KEY=<app key>`, `AGENT_MODEL=anthropic/claude-haiku-5.5`
      (`railway variables --set AGENT_MODEL=anthropic/claude-haiku-5.5`). After A1 lands also set
      `AUTH_SECRET=<random 32+ chars>` and remove `DEMO_KEY`.

---

## Lane A: accounts and ownership (`apps/api/` + `contracts/API.md`) — **critical path**

### A1. Email + password accounts, sessions, workplace ownership (L)
**Files:** `apps/api/src/shiftwright_api/` (new `auth.py`, `db.py`, `main.py`, `settings.py`, `models.py`),
`apps/api/tests/`, `contracts/API.md` (auth section only; David approved via this list), `.env.example`.

API (the web lane builds against exactly this):

| Method | Path | Body → Response |
|---|---|---|
| POST | `/api/auth/signup` | `{email, password, name}` → `{user: {id, email, name}}` + session cookie. 409 if email exists. |
| POST | `/api/auth/login` | `{email, password}` → `{user}` + cookie. 401 on bad credentials (same message for unknown email). |
| POST | `/api/auth/logout` | → 204, clears cookie |
| GET | `/api/auth/me` | → `{user}` or 401 |
| GET | `/api/workplaces` | → `{workplaces: [{id, name, sector, city, state, updated_at, has_schedule}]}` (mine only) |
| POST | `/api/workplaces/sample` | `{template}` → `StoreConfig`: a copy of a demo store, owned by me, named "Sample: …" |

- Tables: `users(id, email UNIQUE COLLATE NOCASE, name, pw_hash, created_at)`,
  `sessions(token, user_id, created_at, expires_at)`, `stores.owner_id` (migrate: add column if missing).
- Passwords: stdlib `hashlib.scrypt` with a random salt per user; constant-time compare. Min length 8.
  Sessions: 32-byte random token, cookie `sw_session`, `HttpOnly`, `SameSite=Lax`, `Secure` when the
  request is https, 30-day expiry.
- `POST /api/stores` sets `owner_id` to the caller. **Every** `/api/stores/{id}/...` route checks ownership
  and returns **404** (not 403) for someone else's store.
- Public routes: `/api/health`, `/api/auth/*`, `/api/templates`, `/api/sms/inbound`, static web files.
  Everything else under `/api` requires a session.
- `AUTH_REQUIRED` setting: default **true**; tests that predate auth use a fixture that signs up a user and
  reuses its client. Remove the `DEMO_KEY` middleware (`main.py` ~line 83) when auth is on.
- Light abuse limits: 10 signup/login attempts per IP per 10 min (in-memory is fine).
- Outreach stays `MESSENGER=mock` in production; keep the existing SMS allowlist.

**Tests first:** signup/login/logout/me; duplicate email 409; wrong password 401; user B gets 404 on user A's
store for config, solve, chat, fix, outreach; public routes still public; sample workplace is owned and
independent of the template.
**Done when:** all API tests green with auth on, and `apps/api/scripts/smoke.py` updated to sign up first.

### A2. Workplace basics on create (S, after A1)
`POST /api/stores` with template `empty` accepts `{name, sector, business_description, jurisdiction}` and
saves them, so the chat starts from "I know you're a taqueria in Chicago" instead of re-asking.
**Done when:** the onboarding agent's first readiness check shows business basics done (test with the fake LLM).

### A3. "Try it with a sample business": one call creates a workplace and its kickoff (M, after A1 and E4)
The user should **watch** Shiftwright set up a business, not do chores. One endpoint does the setup work:

`POST /api/workplaces/generated` `{sector, size?, difficulty?, state?, city?, seed?}` →
`{store_id, company_name, kickoff: {message, attachments: [{kind, filename, row_count}]}}`
- Builds a company with `shiftwright_scenarios.make_dataset`, creates a store owned by the caller
  (template `empty`, `name`/`sector`/`jurisdiction` from the dataset; nothing else prefilled, so the agent
  really does the setup), and runs the existing import **preview** for each CSV (roster → training →
  availability → forecast → history), caching the previews server-side exactly like `/import/{kind}` does.
  Nothing is committed yet.
- `kickoff.message` is the generated manager's own words (`narrative`), ending "My exports are attached."
- Chat: `POST /chat` accepts an optional `attachments: [{kind}]` on a user message. The loop tells the agent
  which previews are attached; `onboard.md` gets one line: "If the leader attached files, start by showing
  `ask_csv_import` for each, in import order, then continue setup from what they imported and said."
- `GET /api/workplaces/{id}/sample-data.zip` keeps the download (E4's zip) for anyone who wants the files.
- Requires a session; 5 generated workplaces per user per 10 min. Document both routes and the
  `attachments` field in `contracts/API.md`.
**Done when:** tests: auth required; a generated workplace is owned, has 0 employees before the cards are
submitted, and reaches `readiness.ready` after scripted `accept_prefill` answers for an `easy` restaurant;
bad values 400; rate limit.

---

## Lane B: product shell (`apps/web/` only) — start now against the Lane A table, wire up when A1 lands

### B1. Routes and auth screens (M)
- Add routing (`react-router-dom` if not present): `/` landing, `/signup`, `/login`, `/workplaces`,
  `/workplaces/new`, `/w/:id` (the workspace). Unauthenticated users on app routes → `/login`.
- **Landing (`/`):** one headline ("Legal, lowest-cost schedules for hourly teams, in minutes."), three short
  proof points (builds the week in seconds · follows the labor law where you are · fixes call-outs and
  texts your team), **Get started** / **Sign in**. No demo store, no tabs.
- Signup/login forms with inline errors; after signup → `/workplaces/new`.
- Remove the auto-create-a-store bootstrap in `App.tsx` (lines ~40–60) and the "Mock API" pill from
  production builds (keep mock for `npm run dev` with `?api=mock`).

### B2. Create a workplace (S)
`/workplaces/new`: three fields: **Name**, **What kind of business?** (Restaurant/café · Retail store · Hotel ·
Other, mapped to `sector`), **City, State**. Optional one-line description. Submit → `POST /api/stores` →
`/w/:id`. The other big choice on this screen is B7's **"Try it with a sample business"**. The
hand-tuned demo stores (`/api/workplaces/sample`) stay reachable from the workplace switcher for rehearsed demos.

### B3. Workplace switcher (S)
Replace the "Store ▾ / Load a demo store" menu with **My workplaces** (list from `/api/workplaces`, current one
checked, "+ New workplace", "Sign out"). Samples appear only under "Explore a sample".

### B4. Guided setup instead of the 15-item checklist (M)
- Until the first schedule exists, the workspace is **setup mode**: chat centered and wide; a slim step
  tracker on the left: **Business → Hours & budget → Team → Staffing → Rules → Build**.
- Map readiness checks to steps (store basics + law → Business; budget → Hours & budget; roles, employees,
  training, hazard tags, minors → Team; demand + priorities → Staffing; provisional rules → Rules). A step is
  done when all its checks pass; hovering shows the plain-language detail.
- One **Build my schedule** button, enabled when ready (or "Build anyway" with a one-line warning).
- After the first build → **workspace mode** (B5). The chat collapses to a side drawer ("Ask Shiftwright").

**Bugs found in QA (04:45), fold into B1/B2/B4:**
- **The first-visit store is the big-box template** (`VITE_STORE_TEMPLATE` defaults to `bigbox_mid` in
  `App.tsx`), so "Set up my store" for a coffee shop starts with 14 retail roles nobody is trained for and
  8am–10pm hours. Every new workplace must start from template `empty` (B1 removes the auto-create; B2
  creates `empty` with the form's basics).
- **Build works on an empty store and shows "Coverage 100% · 0 hard violations ✓" for 0 shifts.** True but
  misleading. In B4: the Build button stays disabled until people, training and staffing exist (readiness
  `employees`, `training`, `demand`), with one plain line saying what's missing. Anywhere coverage is shown
  with no demand, show "—", not 100%.

### B5. Workspace mode: fewer, clearer tabs (M)
- Tabs: **Schedule** (grid + stats; coverage heatmap as a toggle inside it) · **Call-outs** (current Fix tab)
  · **Team & rules** (Store + Rulebook merged) · **Compliance** (receipt).
- Header: workplace name, location, week; nothing else.
- Mark call-in shifts in the grid (badge) — listed as open in `apps/web/STATUS.md`.

### B6. Plain-language pass (S, last in lane)
Grep the UI copy and replace engineer words: "validator" → "compliance check", "law pack / N rules" →
"Labor rules for {city, state}", "slots" → "time blocks", raw ids like `powered_industrial_truck` → their
labels ("Forklift / powered industrial truck"), "infeasible" → "can't be fully covered under your rules"
(with the reason). The conflict menu shows rule names, not ids.

### B7. "Try it with a sample business": watch it set itself up (M, after B2 and B4; wire to A3)
On `/workplaces/new`, next to the create form, one big secondary choice: **"Try it with a sample business"**
with two cards, **Restaurant** and **Retail store**, and a small "More options" (city/state, size, difficulty:
Clean · Tight budget · Legal traps · Messy exports, seed). One click →
1. `POST /api/workplaces/generated` → go straight to `/w/:id` in setup mode (B4).
2. The chat opens with the manager's message already sent, showing file chips for the attached CSVs, and the
   agent starts working at once (streamed text, tool activity line, cards).
3. **Autopilot, on by default for sample businesses:** routine cards (`csv_import` mappings, `store_basics`,
   `payroll`, `roles`, `training_matrix`, `department_staffing`, `events`) show their prefilled content,
   highlight for ~2 s with a "Looks right, continuing…" countdown, then submit as-is. Any click on the card
   stops the countdown and hands control to the user. **Decisions stay with the user:** `confirm_tags`
   (e.g. "Blake is 15 and trained on the fryer"), `propose_rule` hard/soft, `ask_tradeoff`, `conflict_menu`
   never auto-submit. Those are the moments worth watching.
4. When setup finishes, the agent offers to build; one click shows the schedule.
- A thin "Autopilot on · Pause" toggle in the chat header. Real (non-sample) workplaces default to off.
- Small link under the cards: "Download this company's files" (the A3 zip).
Until A3 lands, build against the route's shape using the mock API's generated store.
**Done when:** from `/workplaces/new`, one click on Restaurant reaches a built schedule with the user clicking
only on decision cards; a test covers autopilot submit, user-interrupt and the never-auto decision cards.

**Lane B done when:** a fresh visitor can sign up → create "Harbor Grill" (restaurant, Chicago) → finish
setup in chat → build → see the schedule, without seeing a demo store, a dev pill, or an internal id.
Playwright or Vitest coverage for: auth redirect, create workplace, setup → workspace mode switch.

---

## Lane C: engine (`packages/engine/` only)

### C1. Fix-plan correctness G1–G3 (M) — demo-critical
Findings from the validator's audit, in `packages/validator/STATUS.md` (~lines 169–190) and SEMANTICS #24:
- **G1:** changes that appear only in `schedule_if_all_accept` (Seattle e011, e058) must be listed as actions
  or call-in candidates and priced; or not made. SEMANTICS #24: immediate actions apply to both schedules.
- **G2:** predictive-scheduling grace: only changes **shorter than** `grace_minutes` are free.
- **G3:** Seattle group offer: the exemption covers only the absent coworker's hours.
**Done when:** `uv run python packages/validator/scripts/audit_fix.py --all-fww` reports no G1–G3 findings
and every engine test stays green.

### C2. Split shifts (M, after C1) — demo-critical: Harbor Grill's story is "doubles are normal here"
SEMANTICS #23, `Store.max_shifts_per_day`. In `model.py` ~line 98–105 the per-day constraint is
`sum(y) == w`; change to `sum(y) <= N*w` and `sum(y) >= w` (keep `works[e,d]` boolean so max-days rules stay
correct). Rest-between-shifts (~lines 264–266) assumes one shift per day: handle split days (rest within a
day per SEMANTICS #23, rest across days from last end to next first start). Infeasibility proofs must hold
under the max. **Done when:** S legal_trap CA solves feasible with 0 hard violations (WS4 set
`max_shifts_per_day=2` there), the validator's `audit_engine.py` passes on it, all engine tests green.

### C3. Coverage first, then cost (M–L, after C2) — **deadline 10:00**, else keep current behavior for the demo
David's call: money must never decide whether an hour gets covered. Today the objective trades each
uncovered hour's `gap_penalty_per_hour` against wages, so a cheap enough gap is "worth leaving". Make it
**lexicographic**:
1. Maximize covered demand (person-minutes), **tier by tier**: roles ordered by `gap_penalty_per_hour`,
   highest tier first. The penalty becomes a *rank*, not a price: a higher tier's coverage is never traded
   for a lower tier's or for money.
2. Only among schedules that tie on coverage at every tier, minimize cost (wages + OT + law premiums + soft
   penalties).
- Hard rules unchanged: budget hours/dollar caps, overtime off, laws, training, availability. With the cap
  binding, Must-cover demand is filled first and the rest of the gaps are reported with real reasons.
- `cheaper_to_leave_gap` must no longer appear for a gap that someone legal, available, trained and within
  budget could fill.
- Reported metrics keep today's formulas (`objective_dollars`, `gap_penalty_dollars`) so the validator's
  recompute still matches; only the optimization order changes.
- Implementation is yours (sequential solves per tier with coverage locked, or tier weights that strictly
  dominate total cost; the existing two-phase solve and day LNS are the natural places). Performance bar
  unchanged: demo store ≤ 30 s, fixer ≤ 10 s.
**Contract (David approved via this list):** add SEMANTICS #25 ("objective is lexicographic: coverage by
priority tier, then cost; `gap_penalty_per_hour` orders tiers; metrics formulas unchanged") and a docstring
note on `Role.gap_penalty_per_hour`. No schema change.
**API follow-up (C3b, `apps/api` only, after C3 lands):** in `priorities.py`, map levels to fixed tier values
(`must_cover` 300, `important` 200, `nice_to_have` 100) instead of wage multiples, and drop the readiness
"priority below pay" sub-check (any positive priority now gets covered when possible).
**Evals follow-up (C3c, `packages/evals`):** compare wage cost (not objective) between systems; rescore for free.
**Done when:** all four city demo stores + Harbor Grill solve with 0 hard violations, coverage ≥ today's on
each, within budget, ≤ 30 s; validator `audit_engine.py` agrees; engine, validator and API suites green;
`real-quick-3` rescore (no spend) in `packages/evals/STATUS.md`.

---

## Lane D: law data (`data/laws/` only)

### D1. Hazardous-job rules for minors beyond forklifts (M) — makes the restaurant "law catch" work
Today the only encoded hazard rule is HO 7 (forklifts), so Harbor Grill's `fryer` / `meat_slicer` tags do
nothing. From **29 CFR Part 570** (read the eCFR / law.cornell.edu text; no memory, no secondary sources
alone), add `minor_prohibited_roles` rules to `federal.json` with `age_below`, `age_min`, `role_tags`
from `ROLE_TAGS`, citation and excerpt:
- meat-processing / slicing machines → `meat_slicer`; power-driven bakery machines → `bakery_machine`;
  paper balers / compactors → `baler_compactor`; motor-vehicle driving → `motor_vehicle_driving`;
  power saws → `power_saw`; for ages 14–15, the cooking and fryer limits in § 570.34 → `cooking` / `fryer`
  (record the exceptions in `notes` if they can't be expressed).
**Done when:** data tests green; `resolve("IL","chicago")` returns them; the Harbor Grill demo store shows a
minor kept off the fryer on the Compliance tab (coordinator verifies after merge).

Everything else in WS3's queue (MS/NM minors, more effective dates) is **parked**.

---

## Lane E: scenarios and evals (small)

### E1. Food scenario CSV export bug (S) — `packages/scenarios/`
`write_exports` raises `KeyError: 'management'` for the food store, so the realistic eval skips it.
**Done when:** `write_exports(generate(..., food...))` works and has a test.

### E4. Test-company dataset builder (S, after E1) — `packages/scenarios/`
The generator already exists (`generate(seed, size, difficulty, jurisdiction, sector)` + `write_exports`);
expose it as one function and a CLI:
- `make_dataset(sector, size, difficulty, state, city, seed) -> dict[str, bytes]` returning
  `roster.csv`, `training.csv`, `availability.csv`, `forecast.csv`, `history.csv`, `README.txt`
  (company name, location, the manager's `narrative` to paste into the chat, import order), and
  `ANSWER_KEY.txt` (the planted traps from `expected`: minors on hazard roles, sub-minimum wages, the
  narrative's omissions and contradiction, `expected.infeasible`), for whoever is checking the result.
- `make_dataset_zip(...) -> bytes` (zip of the above, folder named after the company).
- CLI: `uv run python -m shiftwright_scenarios.make_dataset --sector food --size S --difficulty legal_trap
  --state IL --city chicago --seed 42 --out <dir>`.
- `seed` omitted → random, and the seed is printed in README.txt so any company can be regenerated exactly.
- Allowed values: sector `retail|food`; size `S|M` (no `L`, too slow to import live); difficulty
  `easy|normal|tight|legal_trap|messy` (no `infeasible` in the button). Reject anything else.
**Done when:** tests cover every sector × difficulty at size S (files present, CSVs re-import through the
existing `import_packs/packs_harness.py` flow to `readiness.ready` for `easy`), same seed → byte-identical zip.

### E2. Re-score evals for free after C1/C2 (S) — `packages/evals/`
`uv run python -m shiftwright_evals --quick --rescore-from real-quick-1 --run-id real-quick-2` (no API spend).
Drop `SUSPECT_EXPECTED` for S legal_trap CA if C2 made it pass. Update `packages/evals/STATUS.md` with the table.

### E3. Real realistic-eval run (needs David's OK + the evals key)
`uv run python -m shiftwright_evals.estimate --quick --suite realistic` first; budget guard ≤ $20. Run only
after B/A are merged (the Shiftwright side uses the real API). This produces the pitch's headline chart.

---

## After merges (coordinator + David)

- [ ] Deploy, then **full rehearsal on the deployed URL** with a brand-new account: sign up → create Harbor Grill
      (Chicago) → setup in chat (Haiku) → build → minor kept off the fryer → Saturday call-outs → outreach.
      Log every rough edge; fix the top ones before 13:00.
- [ ] Record the backup demo video.
- [ ] Pitch numbers come only from `packages/evals/reports/*`.

## Parked (roadmap slide, not tonight)
Contract v1.6 custom rules (`briefs/CONTRACT-v1.6.md`) · live Twilio · pattern mining · remaining state research.

## Suggested order to 13:00
| When | Lane A | Lane B | Lane C | Lane D | Lane E |
|---|---|---|---|---|---|
| now–06:00 | A1 | B1, B2 (against the table above) | C1 | D1 | E1 |
| 06:00–09:00 | A2, A3, C3b | B3, B4, B7 (wired to A1/A3) | C3 (deadline 10:00) | — | E4, E2, C3c |
| 09:00–11:00 | fixes | B5, B6 | fixes | — | E3 (if approved) |
| 11:00–13:00 | **rehearse on deploy, fix only what breaks the demo** | | | | |
