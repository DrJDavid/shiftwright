# WS6 status — API + chat agent + messaging

_Last updated: 2026-11-06 ~22:45 CT_

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

**In progress / next (M2–M3):** CSV import (`/import/{kind}` + commit, LLM column mapping), fix endpoint,
Messenger (mock + Twilio) + outreach orchestrator + `/api/sms/*`, Dockerfile/railway config, smoke script.

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
- Contract gap to raise: `/fix` returns `FixPlan` but `/outreach/start` takes `plan_id`; FixPlan has no id.
  Plan: return FixPlan JSON plus a top-level `plan_id` key (extra key) and file `contracts/requests/ws6-plan-id.md`.
