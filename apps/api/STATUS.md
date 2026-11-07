# WS6 status — API + chat agent + messaging

_Last updated: 2026-11-07 ~00:45 CT (rebased on main c17640a)_

**Done (M1):**
- `shiftwright_api.main:app` (lazy; `create_app(settings, llm)` factory for tests). SQLite via plain sqlite3
  (`db.py`): stores (config JSON + version), audit_log `(version, tool_name, args, actor)`, schedules,
  transcripts, kv (tradeoff choices / later fix plans + outreach), messages.
- REST: `GET /api/health`, `POST /api/stores` (templates `empty` | `bigbox_small` | `bigbox_mid`),
  `GET/PUT /api/stores/{id}/config` (PUT = full replace, validated, bumps `config_version`, 422 on invalid),
  `GET /readiness` (checks in API.md order), `POST /solve` → `{schedule, validation}`, `POST /validate`,
  `GET /schedule`, `POST /gaps/explain` (deterministic phrasing of engine reasons, no LLM, no added facts),
  `GET /api/laws/resolve`. Extra (not in API.md): `GET /api/stores/{id}/audit`.
- Chat SSE: `POST /chat` streams `text | card | config | tool | done | error`; card tools pause the turn until
  `POST /chat/card` (404 if no such pending card; 30-min timeout → `{cancelled:true}`). Server keeps the
  canonical transcript (OpenAI message format); dangling tool calls after a disconnect are repaired as cancelled.
  One turn per store at a time (409 otherwise).
- Headless mode: `POST /chat?auto_cards=scripted` with body field `card_script: {card_type: [result, ...]}`
  (consumed in order; a card with no scripted answer gets `{cancelled: true}`).
- All 11 card tools, all 10 mutation tools, all 6 read/compute tools from the brief. Mutations validate the
  whole config against the contracts; errors go back to the LLM, nothing saved.
- LLM: `OpenRouterClient` (reads `OPENROUTER_API_KEY`, `AGENT_MODEL`), `FakeLLM` + `call/say/calls` helpers for tests.
  No key → chat emits an `error` event saying so.
- Prompts in `apps/api/prompts/` (`core.md` + `onboard.md` / `review.md` / `fix.md`, versioned in a header comment).
- Web dist served at `/` if `apps/web/dist/index.html` exists (or `WEB_DIST`).
- Tests (`apps/api/tests`): contract tests for every implemented endpoint, SSE text/cards/config, real-server
  card pause→resume, scripted onboarding from `empty` to `readiness.ready = true`, log_unmodeled, lookup_law.

**Done (M2/M3 backend pieces):**
- CSV import: `POST /import/{kind}` (multipart) → `ImportPreview` (mapping = source column → our field | null;
  name-matching heuristic always, LLM mapping from headers + 5 sample rows when a key is set; nothing saved),
  `POST /import/{kind}/commit` `{mapping, rows}` → `StoreConfig`. If the client sends only the preview rows, the
  server uses its cached full parse. Kinds: roster (DOB→age, phone→E.164, `$` wages, FT/PT), training (long format),
  availability (wide `Avail Mon` windows → `unavailable` complements; OFF = whole day), forecast (per-slot or
  windowed rows, merged), history (stored for mining). Unknown departments/roles are added with
  "default, provisional — review" descriptions ($0/h gap penalty for unknown roles) and a warning.
- `POST /fix` → `FixPlan` + `plan_id`; `POST /outreach/start`, `GET /outreach`; `POST /api/sms/inbound`
  (Twilio form, signature checked against `PUBLIC_BASE_URL` + path, TwiML reply); `POST /api/sms/mock-reply`.
- Messenger: `MockMessenger` (default) and `TwilioMessenger` (REST send). Bad Twilio env → falls back to mock with
  a warning in `/api/health.warnings`. Replies: keywords first, helper-LLM fallback, `question` stays in the
  thread for the leader and outreach keeps waiting.
- Orchestrator: rank 1 → wait (`OUTREACH_TIMEOUT_S`, default 90) → accept: append their shift, recompute metrics via
  the validator, save schedule, re-run `fix_day`; empty queue ⇒ `filled`. Decline/timeout ⇒ declined list, re-run
  `fix_day`, text next; nobody left ⇒ `exhausted`. Message copy names role, day, time, $/hr, ends "Reply YES or NO".
- Deploy: `apps/api/deploy/Dockerfile` (build from repo root; builds web, serves it), `apps/api/deploy/railway.toml`,
  `apps/api/scripts/smoke.py` (health → create store → load demo/tiny fixture if present → readiness → solve).
- Tests: 43 in `apps/api/tests` (+2 live-LLM, skipped without a key), green against real `tiny_store.json` + WS3 resolver. Outreach test uses faked `fix_day`/`validate`.

**Done (v1.1 + hardening, this slice):**
- `/fix` returns a plain `FixPlan` with `plan_id` filled by the API (no extra top-level key).
- Readiness check `minimum_wage` ("Wages at or above minimum wage", before `provisional_rules`): highest
  `minimum_wage` rule in the law pack with `effective` ≤ `Store.week_start`; failing detail names each employee and
  wage, e.g. `Below the $7.25/hr minimum (US.minimum_wage.1): <name> ($5.00)`. Blocking.
- Default `AGENT_MODEL` = `anthropic/claude-sonnet-5.5`. `/api/health` has `contract_version` and `demo_key_required`.
- Outreach tests fake `solve_week` too (empty base schedule) and only count proposed `s_*` shifts as accepted, so they
  pass with the stub and with the real WS1 engine (verified in a scratch merge of claude/ws-engine-97a072).
- **SMS allowlist:** `TwilioMessenger` texts only numbers in `SMS_ALLOWLIST` (comma list) ∪ `DEMO_PHONE_1/2`
  (compared by digits, leading US `1` ignored). Anything else: logged (employee id only) and dropped; the outreach
  shows a `system` note "<name>'s number is not on the SMS allowlist; not texted." and moves to the next candidate.
  Empty allowlist + Twilio = nobody is texted. Mock messenger unaffected.
- **Outreach limits:** one active outreach per store (`/outreach/start` → 409 while texting; new
  `POST /api/stores/{id}/outreach/cancel` → `OutreachState`, status `exhausted` + system note). At most
  `MAX_TEXTS_PER_STORE_HOUR` (default 20) outbound texts per store per rolling hour (in memory); hitting it stops the
  outreach with a system note "text limit reached".
- **DEMO_KEY:** if the `DEMO_KEY` env var is set, every non-GET request to `/api/stores*` and `/api/sms/mock-reply`
  needs header `X-Demo-Key: <key>` (else 401 `{"detail": "Missing or wrong X-Demo-Key header."}`). Open: all GETs,
  `/api/health`, `/api/laws/resolve`, `/api/sms/inbound` (Twilio signature-checked when MESSENGER=twilio).
  **For WS7:** read `?key=` from the URL once, store it in `localStorage["shiftwright.demoKey"]`, fall back to
  `import.meta.env.VITE_DEMO_KEY`, and send it as `X-Demo-Key` on every POST/PUT (including the chat SSE `fetch`,
  `/chat/card`, imports, mock-reply). `GET /api/health` → `demo_key_required` tells the UI whether to ask for it.
- Live-agent tests (`test_live_agent.py`, real OpenRouter key, sonnet-5.5): 2/2 pass (~16 s, 2 short turns).

**Done (live chat + outreach stream + onboarding rehearsal):**
- **Token streaming:** `OpenRouterClient.stream()` (OpenAI-style SSE, tool-call fragments reassembled); the chat
  loop forwards each token as a `text` `{delta}` event. Text from separate agent steps in one turn is separated
  by a leading `"\n\n"` in the first delta of the later step, so WS7 can simply concatenate deltas. Clients
  without `stream()` (FakeLLM) still send one delta per step.
- **`GET /api/stores/{id}/outreach/stream`** (SSE, open even with DEMO_KEY). For WS7:
  ```
  event: state
  data: <OutreachState JSON, same shape as GET /outreach>
  ```
  First snapshot immediately, then one on every change (text sent, reply received, accept/decline, filled,
  exhausted, cancelled). `: ping` comment every 15 s while waiting. **The stream closes after a snapshot whose
  status is not "texting"** (so an idle store gets one `idle` snapshot and closes). Open it right after
  `POST /outreach/start` returns; reopen after starting a new outreach. Use `fetch` + a reader or `EventSource`
  (GET, no headers needed).
- **Onboarding rehearsal** `apps/api/scripts/live_onboard.py`: the live model (sonnet-5.5) onboards Store #0417
  from template `empty` with the demo narrative; a simulated leader answers each card from
  `demo_scenario.json`'s config. Run 1 (prompt v1): ready in 2 turns, 25 LLM steps, ≈1.23M prompt chars;
  problems: grids before events, truck-day 4am crew outside the grid window, Saturday truck day lumped
  with Tue/Thu, re-opened a grid, no spaces between steps' text. Run 2 (prompt v2 + fixes): ready in 3 turns,
  22 steps, ≈0.73M prompt chars, cards in the right order. Both runs: every stated rule mapped correctly
  (min/max shift, always_staffed leader, min rest soft, Reese→truck_unload and Terry→guest service preferred_role,
  Jordan/Casey not_together), "students not before 3pm" logged as unmodeled with an offer to set availability,
  no law stated without `lookup_law`, no invented numbers; it caught the payroll mismatch (below).
- Fixes from the rehearsal: prompts `core v2` / `onboard v2` (events before coverage; one grid per day type,
  split with `days` when needs differ; don't reopen submitted grids; fewer `get_config_summary` calls; handle a
  stated rule in the same turn even if the person isn't on the roster yet). `coverage_grid` window now widens to
  cover events on those days (e.g. `start_minute` = 240 for a 4am truck). Card results over 2,000 chars are
  echoed to the model as a short note (the change is still applied and listed in `changed`).
- `/fix` without the engine: 503 "Call-out fixer (engine.fix_day) has not landed yet." It switches to the real
  `shiftwright_engine.fix_day` automatically once that is exported.

**Next:** use real fixtures once WS4 lands;
outreach against the real `fix_day` once WS1 exports it.

**Coordinator follow-ups (outside my folder):** WS4 fixture mismatch: `demo_scenario.json` narrative says
"Payroll is 1,394 hours" but `config.budget.weekly_hours_cap` is 1393.5 (the agent rightly asks which wins).
`/outreach/stream` and the step-separator rule could go in API.md. add `*.db`, `*.db-wal`, `*.db-shm` to root `.gitignore` (default
`DATABASE_URL` writes `./shiftwright.db`); move/point Railway at `apps/api/deploy/railway.toml`; add
`SMS_ALLOWLIST=`, `DEMO_KEY=`, `MAX_TEXTS_PER_STORE_HOUR=20` to root `.env.example`; optionally document
`POST /outreach/cancel` in API.md. (ws6-fixplan-plan-id request: accepted in v1.1, adopted.)

**Stubs (auto-replaced at call time when the real function exists; `/api/health` lists active ones in `stubs`):**
- `engine.solve_week` → no shifts; every demand block is a priced gap; `produced_by="stub:engine"`,
  `solver_stats.stub=true`. Coverage/penalty computed from demand, not invented.
- `engine.fix_day` → 503 "not landed". `engine.explain_gap` → returns the gap's own reasons. `find_conflicts` → None.
- `validator.validate` → certifies only schedules with zero shifts; otherwise 503 (won't fake a pass).
- Labor law: stub removed; `shiftwright_laws.resolve` is called directly for `/api/laws/resolve`, `lookup_law`, readiness and solve.
- `insights.mine_patterns` → `[]`.

**Blocked on:** nothing. Real outreach needs WS1 to export `fix_day` (still 503 via stub).

**Shortcuts / decisions to review:**
- Card results with config payloads are applied by the server (actor `leader`) and returned to the LLM as the tool
  result, rather than relying on the LLM to call the matching mutation. The LLM still sees the full result.
- `coverage_grid` props add `days` and `start_minute` (slot 0 = earliest open − pre_open on those days) so the grid
  is unambiguous. `day_type` → days: weekday = Mon–Fri, saturday = 5, sunday = 6, excluding truck days;
  truck_day = days with a truck event. Submitting replaces non-event demand for those days/roles.
- Template roles carry placeholder `gap_penalty_per_hour` values with description "Template default — review."
  (Role has no `source` field). Templates have no employees/demand and a 0-hour cap, so readiness stays red.
- `/gaps/explain` text is a deterministic template over engine reasons (no LLM call) — safer and instant.
- `/outreach/cancel` is an extra endpoint (not in API.md). Text-rate counters reset on restart.
- Outreach state lives in memory per process (snapshotted to SQLite for GET after restart, but a running outreach
  does not resume after a restart).
