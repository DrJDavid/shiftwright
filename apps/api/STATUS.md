# WS6 status — API + chat agent + messaging

_Last updated: 2026-11-07 ~09:40 CT (rebased on main 5287a2f, WS3 tipped + hazard law)_

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
- Tests: 75 in `apps/api/tests` (+2 live-LLM skipped without a key, +1 demo e2e skipped until fix_day), green against real `tiny_store.json` + WS3 resolver. Outreach test uses faked `fix_day`/`validate`.

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

**Done (v1.4: outreach modes, templates list, e2e with the real fix_day):**
- Modes use the contract literals `one_to_one` | `group_offer` (OutreachState.mode = FixPlan.outreach_mode).
  `/fix` fills `FixRequest.outreach_mode` (body `outreach_mode` overrides) from the law pack via
  `predictive.preferred_mode`: `group_offer` when an applicable rule needs a group message for the exemption and
  we can word its statements, else `one_to_one`. Re-fixes during outreach pass the run's mode. Outreach is sent
  in **the plan's** mode; premium status follows that mode (Seattle one_to_one ⇒ owed).
- `OutreachState.premium.by_employee` (proposal for API.md): `[{employee_id, premium_pay_dollars, law_rule_ids,
  note}]` copied from the plan's `OutreachCandidate`s (the receipt's line items). If the status is owed and every
  amount is $0, the note says the engine didn't compute a premium.
- `GET /api/templates` → `{templates: [{id, label, jurisdiction}]}`: empty / bigbox_small / bigbox_mid
  (jurisdiction null: request supplies it) + every fixture store that loads here (demo, tiny, demo_<locality>
  when WS4's variants exist, any `fixtures/demo_store_<x>.json`).
- `ImportPreview.required_any_of` (proposal for API.md): `[{need: string, any_of: string[][]}]`; a need is met when
  all fields of any alternative are mapped; `unmapped_required` is exactly the unmet needs (roster `name` ←
  `name` | `first_name`+`last_name`; `age` ← `age` | `birth_date`; availability ← any `avail_*`).
- **E2E with the real engine** (`scripts/demo_outreach.py`, scripted mock, in-process): Austin demo store, Saturday
  06:04 call-outs e034/e052/e053: solve 26.4 s (203 shifts, 94.8%), fix 0.7 s (24 actions, 6 in queue, 93.0% →
  best 94.3%), outreach **filled in 22.7 s** with 4 s reply delay (first text 0.01 s): e026 declines → e038 asks
  "What time?", gets the auto-answer, accepts → e022 accepts → e012 accepts; final coverage 95.1%. The e2e test
  (`tests/test_demo_outreach.py`) now runs (fix_day exists) with 0.05 s delays.
  What-ifs (`--city=WA/seattle`, `--city=IL/chicago`; demo store under that city's law, wages floored at its
  minimum): Chicago one_to_one, every text says "Accepting is voluntary and you may decline.", premium exempt,
  filled in 11.7 s (1 s delay). Seattle: the API asked for `group_offer` but **the engine returned
  `outreach_mode: one_to_one`** and $0 premiums (WS1's fix_day doesn't read `FixRequest.outreach_mode` or price
  Seattle yet), so outreach went one-to-one with premium status owed ($0 priced); filled in 65 s (fix 6.9 s).

**Done (group-offer fix + corporate demand conversions):**
- **Group waves offer each person their own proposed shift; a YES fills only that shift.** After an accept the
  API re-runs fix_day: others in the wave whose exact offer is still in the new queue keep waiting; if the engine
  moved their shift they get `"Update: <new offer>"` and must answer again (replies to the old offer are dropped);
  only people whose offer is no longer needed get "Thanks! This shift has been filled". A wave with fewer than
  `exemption_min_recipients` people never says "mass communication" (only the voluntary sentence; premium owed).
  Tests: different-shift recipients both accept and both are booked; moved shift re-offered, old YES ignored;
  single-candidate wave wording. Seattle e2e (`--template=demo_seattle`, 1 s delay): solve 22–29 s, fix
  (group_offer) 2.6 s, filled in ~32 s; every booked shift equals the offer that person said YES to.
- **Demand imports** (packages/scenarios/import_packs/demand/README.md; `demand.py`; all 14 spec/bug xfails pass,
  markers removed; the two "today" tests the specs supersede are marked skip with the reason):
  - Spec 0: every demand import replaces corporate demand only for the (role, day) pairs it produces.
  - Spec 2: forecast `Days` maps to `day`; `Mon-Thu`, `Fri-Sun`/`Fri-Mon` (wrap), `Tue/Thu/Sat`, `Sat,Sun`,
    `Mon & Wed`, `Daily`/`All`/`Every day` expand to one requirement per day. Dated rows outside the week:
    warn and **skip** (was: use the weekday).
  - Spec 3: kinds `labor_model` (dept, role, share, window_start, window_end; stored per store, upserted by
    dept+role) and `labor_hours` (wide Mon..Sun columns or long dept/day/hours, optional Week Total, TOTAL row);
    round-half-up units, cumulative-rounding spread, exact Fractions; closed-day hours dropped (warned);
    "Need a labor model for <dept>" unless the dept has exactly one role; TOTAL sets the hours cap only if it is 0;
    payroll-vs-headcount caveat in the warnings.
  - Spec 4: kinds `labor_standards` (role, driver, units_per_staff_hour, min_hc, max_hc, max_duration_hours;
    stored, upserted by role) and `sales_forecast` (day/date, hour, transactions | sales | online_orders):
    clamp(ceil(driver / standard)), fixed → min; 422 "Import labor standards first." without standards.
  - Spec 5: kind `workload` (day/date, arrival, cases | pieces, truck_id): crew/duration per spec, adds/replaces
    a `truck` Event per truck day, warns when arrival is before the pre-open window.
  - Plausibility: warning when a requirement's headcount exceeds the people trained for the role (50 if none).
  - Commit of `labor_model` / `labor_standards` stores rows and returns the unchanged StoreConfig.
  - **For API.md (ImportKind):** add `labor_model`, `labor_standards`, `labor_hours`, `sales_forecast`, `workload`;
    WS7's csv_import kind list needs them. Agent `ask_csv_import` enum + onboarding prompt v3.2 include them.

**Done (contracts v1.5: any business, cold start):**
- **Prompts** core v3 / onboard v4: any hourly business; ask what the business is first and set `sector` +
  `business_description`; never assume trucks/departments/forecasts/tips; napkin flow (describe a normal week →
  `ask_department_staffing` with `prefill` + `rationale` quoting the leader, labeled a guess → confirm); events by
  sector with `label`; hazard tags explained; tipped cash wage only if stated; rule 12: leader decisions (tags,
  wages, rule strength) are recorded only after they answer. CSV-mapping LLM prompt is industry-neutral.
- **Day groups** from actual open days: `all`, `weekday`, `weekend`, `saturday`, `sunday`, each open day `mon`…`sun`;
  peaks accept those or comma lists (`"fri,sat"`). `coverage_grid` `day_type: "custom"` (days authoritative);
  `truck_day` falls back to custom without truck events. `department_staffing` props add `rationale`
  {role_id: sentence} (default: "A starting guess from your hours and N trained; change it.").
  `events` card props add `kinds` ordered by sector (food: delivery, private_event, catering, promo, other, …).
- **Hazard tagger** (`equipment.py`) for every `ROLE_TAGS` tag by role name/id keywords (e.g. Fry Cook → fryer +
  cooking, Deli Slicer → meat_slicer, Bartender → alcohol_service, Delivery Driver → motor_vehicle_driving;
  not: Server, Host, Dishwasher, Drive Up, Barista, Prep, Cashier). Review state per role
  {status, tags}; confirm/reject applies to that role's auto tags (old {role_id: "auto"} kv still read).
- **Readiness** checks now carry `severity: "ok"|"warn"|"block"` (proposal for API.md; `ok` unchanged). New warn
  checks (ok stays true so they never block): `minors_on_tagged_roles` (names minors trained on any tagged role),
  `business_type` ("Business type not set; every sector's labor rules are applied to be safe."), `staffing_draft`
  (roles with `estimate` demand). `minimum_wage` also checks `tipped_wage_per_hour` (for people trained on a tipped
  role) against `tipped_minimum_wage.cash_wage_per_hour`, or the full minimum when the pack has none.
  Order: … priorities, equipment_roles, minors_on_tagged_roles, business_type, staffing_draft, budget, minimum_wage,
  provisional_rules.
- **Chat-entered people:** `upsert_employee` carries the Employee schema; fills home_department_id (first role's
  department), status part_time, hire_date = week start, E.164 phone. Closed days (`{day, closed: true}`) are
  dropped from store hours (card and `set_store_basics`).
- **Fix/outreach schedule (WS7 issues):** `/outreach/start` and new **`POST /api/stores/{id}/fix/apply {plan_id}`**
  (→ `{schedule, validation}`; idempotent per plan; proposal for API.md) save the plan's `schedule_if_none_accept`
  (the engine's schedule with the called-out shifts removed and the immediate actions applied) as the new
  schedule; outreach then builds on it. Every saved schedule adopts the validator's recomputed metrics and is
  validated again, so no `metrics_mismatch`. `premium.by_employee` refreshes after each re-fix (booked people keep
  their price at booking). Note: the engine drops a called-out shift entirely, including the part before `now`.
  E2E (Austin, real engine, after these): filled in 13.7 s; saved validation passed; no call-out shifts after now.
- **Template `restaurant_small`** (sector food; Manager on Duty, Line Cook [cooking, fryer], Prep, Dishwasher,
  Server [tipped], Host, Bartender [tipped, alcohol_service]; 11 am–10 pm daily; placeholder priorities).
- **Cold-start rehearsal** `scripts/live_coldstart.py` ("30-seat taqueria in Chicago", chat only, owner confirms
  every drafted card). Final run: **ready in 4 owner turns** (5 with the rules turn), 20 LLM calls, ≈0.79M prompt
  chars, 74 s: sector food + description, Tue–Sun per-day hours (Mon closed), 7 roles with server/bartender
  tipped, line cook tagged fryer + cooking (from "the line cooks run the fryer"), bartender alcohol_service,
  10 people from one chat message, per-day staffing from the napkin description (leader source), private event
  "Rehearsal dinner" Sat 4–7 pm +2 servers, produce deliveries Tue/Fri, 4-hour minimum (hard), Kevin's school-day
  limit logged + set as availability. Earlier runs found and fixed: employee upserts failing on missing fields,
  closed-day hours rejected, the agent confirming a tag the owner hadn't answered (rule 12). Not exercised yet:
  tipped cash wages (no `tipped_minimum_wage` in the dataset yet ⇒ full minimum applies, so a $9.48 cash wage
  blocks readiness — correct per SEMANTICS #20) and the fryer rule blocking a 15-year-old (needs WS3's rule).

**Done (taqueria re-run with WS3's tipped + hazard law):**
- Prompts core v3.1 / onboard v4.1: no law statement (incl. "minor-labor rules limit this") without an earlier
  `lookup_law` + rule id; add every person the leader lists (law keeps minors off barred roles; never hold someone
  back over an open tag question).
- Readiness `minors_on_tagged_roles` names the barring rule per minor from the law pack, e.g. "Line cook (fryer,
  cooking): Tommy Ruiz (15; barred by US.minor_prohibited_roles.7)".
- Cold start re-run (Chicago, chat only; owner states a $13.00 tipped cash wage and lists a 15-year-old line cook
  trained on the fryer): ready after 4 owner turns (6 with rules/availability), 18 LLM calls, ≈0.77M prompt chars,
  74 s. Agent called lookup_law before explaining tags; 11 people saved incl. Tommy; tipped_wage_per_hour 13.00 for
  the two servers + bartender; `minimum_wage` passes (Chicago tipped minimum $12.96, IL.chicago.tipped_minimum_wage.1);
  line cook tagged fryer + cooking and confirmed by the owner. Solve (20 s): 48 shifts, 64.3% coverage, **no minor on
  a tagged role**; validator hard codes only `metrics_mismatch`: engine total_wage_cost $6,248.15 vs validator
  $5,750.15 (tipped pay, SEMANTICS #20, not applied by the engine yet; without tipped wages the validator passes).
  Remaining slip: the agent confirmed line cook's tags one turn before the owner's explicit "keep both".

**Next:** re-run the Seattle what-if once WS1 honours `FixRequest.outreach_mode` (expect a group_offer thread).

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

**Blocked on:** nothing.

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
