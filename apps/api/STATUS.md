# WS6 status — API + chat agent + messaging

_Last updated: 2026-11-06 ~23:20 CT_

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
- Tests: 31 in `apps/api/tests` (+2 live-LLM skipped). Outreach acceptance test passes with faked `fix_day`/`validate`.

**Next:** token streaming of agent text; `/outreach/stream` SSE (web polls for now); use real fixtures once WS4 lands;
re-run outreach tests against the real engine once WS1 merges; live-agent tests once a key exists.

**Coordinator follow-ups (outside my folder):** add `*.db`, `*.db-wal`, `*.db-shm` to root `.gitignore` (default
`DATABASE_URL` writes `./shiftwright.db`); move/point Railway at `apps/api/deploy/railway.toml`; see
`contracts/requests/ws6-fixplan-plan-id.md` (FixPlan id + two API.md clarifications).

**Stubs (auto-replaced at call time when the real function exists; `/api/health` lists active ones in `stubs`):**
- `engine.solve_week` → no shifts; every demand block is a priced gap; `produced_by="stub:engine"`,
  `solver_stats.stub=true`. Coverage/penalty computed from demand, not invented.
- `engine.fix_day` → 503 "not landed". `engine.explain_gap` → returns the gap's own reasons. `find_conflicts` → None.
- `validator.validate` → certifies only schedules with zero shifts; otherwise 503 (won't fake a pass).
- `laws.resolve` (looks for `shiftwright_laws.resolve` then `shiftwright_laws.resolver.resolve`) →
  `federal_fallback` pack with **no rules** and a warning. Readiness shows the warning in the detail.
- `insights.mine_patterns` → `[]`.

**Blocked on:** nothing. `OPENROUTER_API_KEY` needed for the live-agent tests (`test_live_agent.py`, skipped without it).

**Shortcuts / decisions to review:**
- Card results with config payloads are applied by the server (actor `leader`) and returned to the LLM as the tool
  result, rather than relying on the LLM to call the matching mutation. The LLM still sees the full result.
- `coverage_grid` props add `days` and `start_minute` (slot 0 = earliest open − pre_open on those days) so the grid
  is unambiguous. `day_type` → days: weekday = Mon–Fri, saturday = 5, sunday = 6, excluding truck days;
  truck_day = days with a truck event. Submitting replaces non-event demand for those days/roles.
- Template roles carry placeholder `gap_penalty_per_hour` values with description "Template default — review."
  (Role has no `source` field). Templates have no employees/demand and a 0-hour cap, so readiness stays red.
- Default `AGENT_MODEL` is `anthropic/claude-sonnet-4.5`; check the strongest tool-calling Claude slug on
  OpenRouter once the key exists and set `AGENT_MODEL`.
- `/gaps/explain` text is a deterministic template over engine reasons (no LLM call) — safer and instant.
- Agent responses are not token-streamed yet: each LLM step arrives as one `text` delta.
- `/fix` returns FixPlan JSON + extra top-level `plan_id` (request filed).
- Outreach state lives in memory per process (snapshotted to SQLite for GET after restart, but a running outreach
  does not resume after a restart).
