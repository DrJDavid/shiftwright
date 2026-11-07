# Shiftwright API & chat protocol — v1.4

Owner: David. Backend (WS6) implements; web (WS7) and evals (WS5) consume.
All bodies are JSON shaped by `contracts/models.py`. TypeScript types are generated
from the JSON Schema (`make types` → `apps/web/src/contracts.ts`); never hand-write them.

## REST endpoints

| Method | Path | Body → Response | Notes |
|---|---|---|---|
| POST | `/api/stores` | `{template?: "bigbox_small"\|"bigbox_mid"\|"empty", name, jurisdiction}` → `StoreConfig` | Creates a store from a template (defaults have `source: default`). v1.2: templates `demo` (Store #0417 Austin, 60 staff) and `tiny` load the WS4 fixtures as-is under a new id; `name`/`jurisdiction` optional for those two. |
| GET | `/api/stores/{id}/config` | → `StoreConfig` | |
| PUT | `/api/stores/{id}/config` | `StoreConfig` → `StoreConfig` | Full replace; bumps `config_version`. Used by cards that edit grids. |
| POST | `/api/stores/{id}/import/{kind}` | multipart CSV → `ImportPreview` | `kind` ∈ roster, training, availability, forecast, history; v1.4 adds labor_model, labor_hours, labor_standards, sales_forecast, workload (corporate demand styles; conversions specified in packages/scenarios/import_packs/demand/README.md). Returns a proposed column mapping + parsed rows; nothing is saved yet. |
| POST | `/api/stores/{id}/import/{kind}/commit` | `{mapping, rows}` → `StoreConfig` | |
| GET | `/api/stores/{id}/readiness` | → `Readiness` | |
| POST | `/api/stores/{id}/solve` | `{time_limit_s?: number}` → `{schedule: Schedule, validation: ValidationReport}` | Always run the validator on engine output too. |
| POST | `/api/stores/{id}/validate` | `Schedule` → `ValidationReport` | Used by evals for baseline schedules. |
| GET | `/api/stores/{id}/schedule` | → latest `{schedule, validation}` | |
| POST | `/api/stores/{id}/gaps/explain` | `{gap: Gap}` → `{text, reasons: GapReason[]}` | LLM phrases engine `reasons`; it may not add facts. |
| POST | `/api/stores/{id}/fix` | `{callouts: CallOut[], day, now}` → `FixPlan` | The API fills `FixPlan.plan_id` (v1.1); pass it to `/outreach/start`. |
| POST | `/api/stores/{id}/outreach/start` | `{plan_id}` → `OutreachState` | Texts candidate rank 1; waits; on decline/timeout moves to the next. |
| POST | `/api/stores/{id}/outreach/cancel` | → `OutreachState` | v1.1. Stops the active outreach (one active outreach per store; a second `/outreach/start` gets 409). |
| GET | `/api/stores/{id}/outreach` | → `OutreachState` | Web polls every 2s (or SSE `/outreach/stream`). |
| GET | `/api/stores/{id}/outreach/stream` | → SSE `event: state`, data = `OutreachState` | v1.1. One snapshot immediately, then on every change; keep-alive ping every 15 s; the stream closes after a snapshot whose status isn't `texting`. |
| POST | `/api/sms/inbound` | Twilio webhook (form-encoded) → TwiML 200 | Validates Twilio signature. |
| POST | `/api/sms/mock-reply` | `{from_phone, body}` → 200 | Only when `MESSENGER=mock`. Same code path as inbound. |
| GET | `/api/laws/resolve?state=TX&city=austin` | → `LawPack` | |
| POST | `/api/stores/{id}/equipment_roles` | `{role_id, decision: "confirm"\|"reject"}` → `StoreConfig` | v1.4. Roles whose names look like powered equipment are tagged `powered_industrial_truck` when created (import or chat); the leader confirms or rejects. Rejected roles are never re-tagged. |
| GET | `/api/stores/{id}/import/{kind}/warnings` | → `{kind, warnings: string[]}` | v1.4. Warnings from the latest commit of that kind; the commit response also sets header `X-Import-Warning-Count`. |
| GET | `/api/templates` | → `{templates: {id, label, jurisdiction}[]}` | v1.4. Store templates available on this server (e.g. `demo`, `demo_chicago`, `demo_seattle`, `demo_sf`, `tiny`, `empty`). |
| GET | `/api/health` | → `{ok, contract_version, messenger, model}` | |

Helper shapes (defined in `apps/api`, mirrored in TS by hand only for these):

```ts
ImportPreview = { kind, columns: string[], proposed_mapping: Record<string,string|null>,
                  unmapped_required: string[], rows_preview: object[], row_count: number, warnings: string[],
                  target_fields: string[], required_fields: string[] }   // v1.2: fields a column may map to / must map
Readiness     = { ready: boolean, checks: {id: string, label: string, ok: boolean, detail: string}[] }
OutreachState = { plan_id, status: "idle"|"texting"|"filled"|"exhausted",
                  current_rank: number|null, messages: (OutboundMessage|InboundMessage)[],
                  accepted_employee_ids: string[], schedule: Schedule,
                  // v1.4
                  mode: "one_to_one"|"group_offer",          // = FixPlan.outreach_mode
                  wave: number, waiting_employee_ids: string[],
                  premium: {status: "not_applicable"|"exempt"|"owed", law_rule_ids: string[], note: string} | null }
```

Readiness checks (in order): store basics, jurisdiction resolved to a LawPack, roles exist,
≥1 employee, every role has ≥1 trained employee, demand exists for every open day,
priorities set (every role with demand has `gap_penalty_per_hour` > 0; v1.4, blocking),
equipment roles reviewed (v1.4, warning only: the protective tag is already applied), budget set, every employee's wage ≥ the law pack's minimum wage (v1.1; names the employees),
no `provisional` constraints older than the current session (warn, not block).

## Chat protocol (Server-Sent Events)

`POST /api/stores/{id}/chat` body: `{mode: "onboard"|"review"|"fix", messages: ChatMessage[]}`
Response is an SSE stream of events:

| event | data | meaning |
|---|---|---|
| `text` | `{delta: string}` | assistant prose, token-streamed. When one turn has several agent steps, the first delta of a later step starts with a blank line, so clients can simply concatenate. |
| `card` | `{card_id, card_type, props}` | render this card inline; the turn PAUSES until the card is submitted |
| `config` | `{config_version, patch_summary: string[]}` | the config changed (web refetches config + readiness) |
| `tool` | `{name, status: "start"\|"done", summary}` | optional activity line ("Ran dry-run solve") |
| `done` | `{}` | turn complete |
| `error` | `{message}` | |

Card submission: `POST /api/stores/{id}/chat/card` `{card_id, result}` → resumes the same
SSE turn (the result becomes the tool result the LLM sees). `result` may be
`{cancelled: true}`.

Headless mode (for evals, v1.1): `POST /api/stores/{id}/chat?auto_cards=scripted` with an extra
body field `card_script: {card_type: [result, ...]}`. Each card of that type takes the next scripted
result, in order; a card with no scripted result left gets `{cancelled: true}`. The SSE stream is the
same as in interactive mode, but no `POST /chat/card` is needed.

`ChatMessage = {role: "user"|"assistant", content: string, card?: {card_id, card_type, props, result}}`
The server keeps the canonical transcript; the client sends only new user messages.
v1.2: a new user message while the previous turn is paused on a card cancels that card (`{cancelled: true}`)
and starts the new turn; 409 only if the previous turn is mid model call.

## Card catalogue (card_type → props → result)

| card_type | props | result |
|---|---|---|
| `store_basics` | prefill `Store` fields | `Partial<Store>` |
| `payroll` | prefill `Budget` | `Budget` |
| `roles` | `{departments, roles}` | `{departments, roles}` |
| `training_matrix` | `{employees:[{id,name}], roles}` | `{employee_id: role_id[]}` |
| `coverage_grid` | `{day_type: "weekday"\|"saturday"\|"sunday"\|"truck_day", roles, slot_minutes, days: int[], start_minute: int, prefill: headcount[role][slot]}` | same grid |
| `events` | `{events}` | `{events}` |
| `department_staffing` | v1.3. `{department: Department, roles: Role[], day_groups: [{id: "weekday"\|"saturday"\|"sunday", days: int[]}], hours: DayHours[], pre_open_minutes, post_close_minutes, suggested: {role_id: RoleStaffing}}` | `{staffing: {role_id: RoleStaffing}}` |
| `csv_import` | `{kind, preview?: ImportPreview}` | `{committed: boolean, rows: number}` |
| `propose_rule` | `{constraint: Constraint, evidence, plain_text}` | `{decision: "hard"\|"soft"\|"not_a_rule", weight_dollars?}` |
| `tradeoff` | `{question, options:[{id,label,cost_dollars,effect}]}` | `{option_id}` |
| `conflict_menu` | `{infeasibility: Infeasibility, options:[{id,label,cost_dollars,patch_summary}]}` | `{option_id}` |
| `employee_availability` | `{employee, parsed: AvailabilityEntry[], original_text}` | `{confirmed: AvailabilityEntry[]}` |

`coverage_grid` (v1.1): `days` are the day indexes the day_type covers (weekday = Mon–Fri,
saturday = 5, sunday = 6, each excluding truck days; truck_day = days with a truck event).
Slot i covers `[start_minute + i*slot_minutes, start_minute + (i+1)*slot_minutes)`.

`department_staffing` (v1.3) is the default way to collect demand when no corporate forecast CSV is imported.
The agent asks one department at a time, prefilled with suggestions; the leader confirms or edits.
```ts
RoleStaffing = { base: number,                                   // people most of the open day
                 peaks: {day_group: string, start: number, end: number, headcount: number}[],
                 open:  {headcount: number, minutes_before_open: number} | null,
                 close: {headcount: number, minutes_after_close: number} | null }
```
The server converts the result into `DemandRequirement`s (`source: leader`; base across open hours per day,
peaks replace base inside their windows, open/close crews in the pre-open/post-close windows), replacing
existing non-event demand for those roles, then the client shows a read-only `coverage_grid`-style preview.
Truck and other event crews come from the `events` card. `coverage_grid` stays as an advanced editor; with `readonly: true` (v1.4) it is a preview that doesn't pause the turn.
Forecast CSVs may carry an optional `duration` column (minutes) for start-only rows (v1.4).

## Environment variables

```
OPENROUTER_API_KEY=
AGENT_MODEL=anthropic/claude-sonnet-5.5
BASELINE_MODELS=x-ai/grok-4.7,anthropic/claude-opus-5.5,openai/gpt-6.1-terra-pro
MESSENGER=mock            # or twilio
TWILIO_ACCOUNT_SID= TWILIO_AUTH_TOKEN= TWILIO_FROM_NUMBER=
PUBLIC_BASE_URL=          # for the Twilio webhook
DATABASE_URL=sqlite:///./shiftwright.db
SMS_ALLOWLIST=            # v1.1: Twilio only texts these + DEMO_PHONE_1/2
DEMO_KEY=                 # v1.1: if set, mutating /api/stores/* routes need header X-Demo-Key (401 otherwise)
MAX_TEXTS_PER_STORE_HOUR=20
MOCK_AUTOREPLY=script     # v1.2, mock only: script (rank 1 declines; rank 2 asks a question, then accepts; rest accept) | prob (seeded draw on est_accept_prob) | off
MOCK_REPLY_DELAY_S=4
MOCK_SEED=417
```
Mock outreach answers an employee's question automatically by restating only the offer's role, day, times and pay.
