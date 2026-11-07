# WS6 — Backend API + chat agent + messaging

**Folder:** `apps/api/` (`shiftwright_api`) · **Oversight:** partner
**Read first:** `SPEC.md`, `contracts/models.py`, `contracts/API.md`

## Goal
Implement `contracts/API.md` exactly: persistence, CSV import, the tool-using chat agent that
turns conversation and CSVs into a `StoreConfig`, solve/validate/fix endpoints, and SMS outreach.

## Pieces
1. **Persistence.** SQLite via SQLModel or plain SQL. Tables: stores (config JSON +
   version), schedules, transcripts, outreach sessions, messages. Every config mutation bumps
   `config_version` and appends to an audit log `(version, tool_name, args, actor)`.
2. **CSV import.** Parse → LLM proposes a column mapping (headers + 5 sample rows only) →
   `ImportPreview` → user confirms on the card → commit. Deterministic parsing after mapping.
   Unknown department/role names: add them as `source: default`, provisional, flagged.
3. **Chat agent loop.** OpenRouter (OpenAI-compatible tool calling), model `AGENT_MODEL`. SSE as
   specified. Modes: `onboard`, `review`, `fix`. The loop: LLM → tool calls → (card tools pause
   until `/chat/card` arrives) → tool results → LLM … until no tool calls.
4. **Tools.**
   - *Cards:* one per card in API.md (`ask_store_basics`, `ask_payroll`, `ask_roles`,
     `ask_training_matrix`, `ask_coverage_grid`, `ask_events`, `ask_csv_import`, `propose_rule`,
     `ask_tradeoff`, `show_conflict_menu`, `confirm_employee_availability`).
   - *Mutations:* `set_store_basics`, `set_budget`, `upsert_role`, `upsert_employee`,
     `set_demand`, `add_event`, `add_constraint`, `set_constraint_status`, `log_unmodeled`,
     `approve_budget_increase` (only after a `tradeoff` card returns that option).
   - *Read/compute:* `get_config_summary`, `readiness_check`, `dry_run_solve` (engine + validator,
     returns metrics, gaps, infeasibility), `explain_gap`, `lookup_law` (resolver only),
     `mine_patterns` (WS8; stub returning [] until it exists).
   Each mutation validates against the contracts and returns the errors to the LLM on failure.
5. **System prompt** (`apps/api/prompts/onboard.md`, etc.; keep in files, version them). Core rules:
   - Use a card whenever input is structured. Ask one thing at a time. Prefer CSV import when the user has exports.
   - Map every rule to a `ConstraintKind`. If none fits, `log_unmodeled` and say so in one sentence.
   - Always ask hard vs. soft, and for soft rules, what it's worth in dollars (use `ask_tradeoff` for the value).
   - Never state a law except from `lookup_law`, always with the citation. Not legal advice.
   - Never state numbers (cost, hours, coverage) except from tool results.
   - Name contradictions; never resolve them silently.
   - Decline out-of-scope requests briefly.
6. **Messenger.** `Messenger` protocol with `send(employee, body)`; `MockMessenger` (stores
   messages, replies via `/api/sms/mock-reply`) and `TwilioMessenger` (REST send; inbound webhook
   with signature validation). Reply interpretation: keyword rules first (yes/y/sure/ok vs
   no/n/can't), LLM fallback for anything else; `question` replies get forwarded to the leader's view.
7. **Outreach orchestrator.** For a `FixPlan`: text rank 1 → wait (demo timeout 90 s,
   configurable) → on accept, commit their shift and recompute; on decline/timeout, add to
   `declined_employee_ids`, re-run `fix_day`, text the next. Stop when coverage targets are met
   or the queue is empty. Message copy: short, names the shift, role, and pay, ends with "Reply YES or NO".
8. **Headless mode** for evals: `POST /api/stores/{id}/chat?auto_cards=scripted` with a script of card answers.

## Deploy
Single service: FastAPI serves `apps/web/dist` at `/`. `Dockerfile` + Railway or Fly config.
`PUBLIC_BASE_URL` set for Twilio. Smoke test script hits `/api/health`, creates the demo store, solves.

## Acceptance tests
- Contract tests: every endpoint's response validates against its model.
- Scripted onboarding of `tiny_store` from scratch via headless chat reaches `readiness.ready = true`.
- The agent, told "Sam is better with customers," calls `log_unmodeled` (or proposes `preferred_role` and asks), and doesn't silently drop it.
- The agent, asked about overtime law, calls `lookup_law` before answering.
- Mock outreach: decline from rank 1 → rank 2 texted within 2 s; accept → schedule updated, coverage recomputed.
