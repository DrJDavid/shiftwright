# WS6 status — API + chat agent + messaging

_Last updated: 2026-11-07 ~05:30 CT (rebased on main eaed15e)_

**Done (M1):**
- `shiftwright_api.main:app` (lazy; `create_app(settings, llm)` factory for tests). SQLite via plain sqlite3
  (`db.py`): stores (config JSON + version), audit_log `(version, tool_name, args, actor)`, schedules,
  transcripts, kv (tradeoff choices / later fix plans + outreach), messages.
- REST: `GET /api/health`, `POST /api/stores` (templates `empty` | `bigbox_small` | `bigbox_mid` | `demo` | `tiny`),
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
- Tests: 63 in `apps/api/tests` (+2 live-LLM skipped without a key, +1 demo e2e skipped until fix_day), green against real `tiny_store.json` + WS3 resolver. Outreach test uses faked `fix_day`/`validate`.

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

**Done (demo-worthy mock outreach + WS7 fixes + fixture templates):**
- **Simulated replies** (mock messenger only; Twilio never auto-replies). `MOCK_AUTOREPLY` = `off` | `script` |
  `prob` (default `script` from env; `/api/health.mock_autoreply` shows the active mode), `MOCK_REPLY_DELAY_S`
  (default 4), `MOCK_SEED` (default 417).
  - `script` (deterministic demo, by order texted in this outreach): 1st person → "Sorry, can't today";
    2nd → "What time?", the system answers, then "Yes I can"; anyone after → "Yes I can".
  - `prob`: accept iff a draw seeded by (seed, plan_id, employee_id) < `est_accept_prob`.
  - A manual `POST /api/sms/mock-reply` from that number cancels the pending simulated reply and wins.
- **Questions get a factual auto-answer** (all messengers): an outbound text restating only the offer's facts:
  "It's Cashier, Sat 10 am to 2 pm, $15.50/hr. Your manager will see any other questions. Reply YES or NO".
  Counts toward the text limit. Outreach keeps waiting.
- **Phone thread for WS7:** `OutreachState.messages` is the thread in time order. Outbound = has `to_employee_id`,
  `to_phone`, `sent_at`, `outreach_rank`. Inbound = `from_phone`, `received_at`, `interpreted_as`. System notes
  (allowlist drop, rate limit, cancel, errors) are inbound with `from_phone: "system"`. SMS times are now 12-hour.
- **Templates `demo` and `tiny`:** `POST /api/stores {"template": "demo"}` (or `"tiny"`) loads
  `shiftwright_scenarios.load_demo_store()` / `load_tiny_store()` as-is under a new store id. `name` and
  `jurisdiction` are optional for these (ignored); still required for the other templates (422 otherwise).
  Verified in the Docker image (`docker build -f apps/api/deploy/Dockerfile .`): health ok, demo store 60 employees,
  readiness green, law pack resolves, web served at `/`. Added `apps/api/deploy/Dockerfile.dockerignore`
  (keeps local `.venv`, `node_modules`, `.env`, `.git`, `.claude` out of the build context).
- **/solve:** if the engine or validator raises (incl. MemoryError), 500 `{"detail": "Schedule engine failed
  (MemoryError: …). Nothing was saved."}`. Note: a local demo-store solve (20 s limit) peaked at ≈3 GB RSS, so a
  1 GB container will OOM before Python can catch anything — WS1's memory work is what fixes that.
- **Readiness details** use names: role names ("Nobody trained for: Guest Service Desk"), day names
  ("No demand on Monday, Tuesday"), and rule notes instead of constraint ids for unconfirmed rules.
- **/gaps/explain** uses 12-hour times ("Cashier Sat 10 am–2:30 pm uncovered (1 short, $120)"); whole-dollar
  amounts drop the cents.
- **ImportPreview** adds `target_fields: string[]` (dropdown options for this kind, in order) and
  `required_fields: string[]` (subset that must be mapped).
- **Card lock:** a new `POST /chat` while the previous turn is parked on a card (e.g. browser closed mid-card)
  cancels that card (`{cancelled: true, reason: "superseded by a new message"}`), ends the old turn, and runs the new
  one. Still 409 if the previous turn is mid-model-call (no card pending). Client disconnect also ends the turn.
- **E2E demo outreach:** `apps/api/scripts/demo_outreach.py [BASE_URL] [--delay=4]` (demo template → solve → /fix
  with the Saturday 06:04 call-outs e034/e052/e053 → start → stream until done; prints timings + thread) and
  `tests/test_demo_outreach.py` — both skip while `engine.fix_day` is stubbed (exit 2 for the script).
  Demo-store solve via the API today: 18 s, 174 shifts, 90.3% coverage, validator passed.

**Done (safety, importer, staffing card, Fair Workweek outreach):**
- **Powered-equipment roles** (`equipment.py`): roles created by a CSV import or in chat (`upsert_role`,
  `roles` card) whose name/id looks like a powered industrial truck (forklift, PIT, reach truck, electric/rider
  pallet jack, order picker lift, hi-lo, scissor/boom lift, ...) get `role_tags[...] = ["powered_industrial_truck"]`
  in the same mutation, so the law pack's `minor_prohibited_roles` applies at once. Classification only, no law.
  Plain "Pallet Jack", "Order Picker", "Shelf Stacker" are not tagged. Review state in kv `equipment_review`
  {role_id: auto|confirmed|rejected}; a rejected role is never re-tagged.
  - `POST /api/stores/{id}/equipment_roles {role_id, decision: "confirm"|"reject"}` → StoreConfig (new).
  - Agent tool `review_equipment_role` (only after the leader answers); tool results carry `equipment_tagged`.
  - Readiness check `equipment_roles` ("Powered-equipment roles"): **ok = true** (protection is already on)
    with detail "Tagged automatically as powered industrial trucks, so minor-labor rules apply: FORKLIFT. Please
    confirm or reject." — not blocking, because blocking would break the CSV-pack tests the coordinator asked me
    not to edit (`test_messy_readiness_blocks`, `test_messy_ready_after_review_fixes`) and the safe default is on.
- **Readiness `priorities`** ("Role priorities set"): blocks when any role with demand has
  `gap_penalty_per_hour` ≤ 0: "Set priorities (what an uncovered hour costs) for: Cashier, ...".
  Check order now: store_basics, jurisdiction, roles, employees, training, demand, **priorities**,
  **equipment_roles**, budget, minimum_wage, provisional_rules.
- **Importer** (all 17 import-pack xfails now pass; markers removed): word-boundary header matching ("Manager"
  no longer → age), two-digit birth years pivot to an age of 14–90 (warned), ages outside 14–90 warned, short
  phones warned (kept), duplicate ids warned (last row wins), "Seas"→seasonal, "Not Available"/"closed"/"-"
  = unavailable (warned), more weekday header variants (Tues/Weds/Thurs), forecast: overnight End column (+1440),
  start-only rows last their group's own spacing (or a new optional `duration` column; one slot only with a
  warning), off-grid rows rolled up per slot at peak headcount (warned), fractional headcount rounded up (warned),
  dates outside the schedule week warned. Not done: `Home Org`/`Punch In` synonyms (the CSV agent's non-xfail
  tests assert they stay unmapped), header-not-on-line-1, non-UTF-8 detection.
- **Commit warnings (proposal for API.md):** commit body unchanged (StoreConfig); response header
  `X-Import-Warning-Count: <n>`; new `GET /api/stores/{id}/import/{kind}/warnings` →
  `{kind, warnings: string[]}` (latest commit of that kind). WS7: after commit, if the header is > 0, GET and show them.
- **`department_staffing` card** (API.md v1.3): tool `ask_department_staffing(department_id, prefill?)`.
  Props as API.md plus `suggestion_note` (always: "Suggested starting point ... Not a forecast, a corporate
  standard or a legal requirement."), `suggestion_basis` {role_id: "N trained"} and `from_chat` (role ids prefilled
  from what the leader said). Suggestion = base 0 (<2 trained), 1, or 2 (≥10 trained); no peaks/crews.
  Result → DemandRequirements exactly per API.md (base over open hours, peaks replace base in their
  day_group window, open/close crews in the pre/post windows, snapped outward to slots), replacing non-event
  demand for those roles. Readiness `demand` accepts it (it is ordinary leader demand).
- **Read-only preview:** tool `show_coverage_preview(day_type)` emits a `coverage_grid` card with
  `props.readonly = true` and does **not** wait (no `/chat/card` needed). WS7: render it without a submit button.
- **Onboarding prompt v3.1:** forecast CSV first, else one staffing card per department (leadership first,
  receiving last), chat answers go into `prefill`, events card then event crews via `set_demand` (source event),
  preview, `coverage_grid` only on request; stated rules proposed once after the roster exists.
  Live rehearsal (v3, before the v3.1 tweaks): ready in 2 turns, 20 LLM calls, ≈0.84M prompt chars, 7 staffing
  cards. Issues seen and addressed in v3.1: rules proposed before the roster then re-proposed; truck crew via open crew.
- **Templates `demo_<locality>`** (demo_chicago, demo_seattle, demo_sf, ...): `load_demo_store(locality=...)`
  if WS4's loader takes it, else `fixtures/demo_store_<locality>.json`; 422 "No demo store for 'x' yet" otherwise.
- **After an accept** the schedule is re-validated (with the law pack) and saved with its ValidationReport.
- **Fair Workweek outreach** (`predictive.py`, params only): applicable `predictive_scheduling` rules
  (employer count unknown ⇒ applies) decide:
  - Seattle (`exemption_requires_group_message`): **group** mode — each wave texts the top
    `exemption_min_recipients` (≥2) at once; each text adds the statements from `exemption_message_must_state`
    ("This is a mass communication sent to several employees. Accepting these hours is voluntary and you may
    decline. Accepting does not earn additional compensation for schedule changes."). First YES wins; others in
    the wave get "Thanks! This shift has been filled, so no action is needed." Fewer candidates than the minimum ⇒
    sent anyway, premium marked owed. A statement we can't word ⇒ sequential, premium owed.
  - Chicago (voluntary exempt + text counts as written): sequential, text says "Accepting is voluntary and you
    may decline." Also added whenever a candidate's `why` says the call-in is voluntary.
  - Otherwise premium owed (amount comes from the engine's plan, never from us).
  - **OutreachState additions (proposal for API.md):** `mode: "sequential"|"group"`, `wave: int`,
    `waiting_employee_ids: string[]`, `premium: {status: "not_applicable"|"exempt"|"owed", law_rule_ids: string[],
    note: string} | null`.
  - **Proposal for WS1/contracts:** `FixRequest.outreach_mode: "sequential"|"group"|null` (API fills it from the
    same params before calling fix_day) so the engine prices group-offer call-ins as exempt and one-to-one
    Seattle texts with the 1-hour premium.
- Mock auto-replies work per recipient in group waves (1st texted declines, 2nd asks then accepts).

**Next:** run `scripts/demo_outreach.py` once WS1 exports `fix_day`, and tune delays/timeouts for the demo.

**Coordinator follow-ups (outside my folder):** WS4 fixture mismatch: `demo_scenario.json` narrative says
"Payroll is 1,394 hours" but `config.budget.weekly_hours_cap` is 1393.5 (the agent rightly asks which wins).
API.md lines for: templates `demo`/`tiny` (+ optional name/jurisdiction), `ImportPreview.target_fields`/
`required_fields`, `MOCK_AUTOREPLY`/`MOCK_REPLY_DELAY_S`/`MOCK_SEED` env vars, question auto-answer, card supersede rule
(and `.env.example` entries for the three MOCK_ vars). Older items: add `*.db`, `*.db-wal`, `*.db-shm` to root `.gitignore` (default
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
- Text-rate counters reset on restart (accepted for the demo).
- Outreach state lives in memory per process (snapshotted to SQLite for GET after restart, but a running outreach
  does not resume after a restart).
