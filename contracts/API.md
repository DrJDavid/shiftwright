# Shiftwright API & chat protocol — v1

Owner: David. Backend (WS6) implements; web (WS7) and evals (WS5) consume.
All bodies are JSON shaped by `contracts/models.py`. TypeScript types are generated
from the JSON Schema (`make types` → `apps/web/src/contracts.ts`); never hand-write them.

## REST endpoints

| Method | Path | Body → Response | Notes |
|---|---|---|---|
| POST | `/api/stores` | `{template?: "bigbox_small"\|"bigbox_mid"\|"empty", name, jurisdiction}` → `StoreConfig` | Creates a store from a template (defaults have `source: default`). |
| GET | `/api/stores/{id}/config` | → `StoreConfig` | |
| PUT | `/api/stores/{id}/config` | `StoreConfig` → `StoreConfig` | Full replace; bumps `config_version`. Used by cards that edit grids. |
| POST | `/api/stores/{id}/import/{kind}` | multipart CSV → `ImportPreview` | `kind` ∈ roster, training, availability, forecast, history. Returns a proposed column mapping + parsed rows; nothing is saved yet. |
| POST | `/api/stores/{id}/import/{kind}/commit` | `{mapping, rows}` → `StoreConfig` | |
| GET | `/api/stores/{id}/readiness` | → `Readiness` | |
| POST | `/api/stores/{id}/solve` | `{time_limit_s?: number}` → `{schedule: Schedule, validation: ValidationReport}` | Always run the validator on engine output too. |
| POST | `/api/stores/{id}/validate` | `Schedule` → `ValidationReport` | Used by evals for baseline schedules. |
| GET | `/api/stores/{id}/schedule` | → latest `{schedule, validation}` | |
| POST | `/api/stores/{id}/gaps/explain` | `{gap: Gap}` → `{text, reasons: GapReason[]}` | LLM phrases engine `reasons`; it may not add facts. |
| POST | `/api/stores/{id}/fix` | `{callouts: CallOut[], day, now}` → `FixPlan` | |
| POST | `/api/stores/{id}/outreach/start` | `{plan_id}` → `OutreachState` | Texts candidate rank 1; waits; on decline/timeout moves to the next. |
| GET | `/api/stores/{id}/outreach` | → `OutreachState` | Web polls every 2s (or SSE `/outreach/stream`). |
| POST | `/api/sms/inbound` | Twilio webhook (form-encoded) → TwiML 200 | Validates Twilio signature. |
| POST | `/api/sms/mock-reply` | `{from_phone, body}` → 200 | Only when `MESSENGER=mock`. Same code path as inbound. |
| GET | `/api/laws/resolve?state=TX&city=austin` | → `LawPack` | |
| GET | `/api/health` | → `{ok, contract_version, messenger, model}` | |

Helper shapes (defined in `apps/api`, mirrored in TS by hand only for these):

```ts
ImportPreview = { kind, columns: string[], proposed_mapping: Record<string,string|null>,
                  unmapped_required: string[], rows_preview: object[], row_count: number, warnings: string[] }
Readiness     = { ready: boolean, checks: {id: string, label: string, ok: boolean, detail: string}[] }
OutreachState = { plan_id, status: "idle"|"texting"|"filled"|"exhausted",
                  current_rank: number|null, messages: (OutboundMessage|InboundMessage)[],
                  accepted_employee_ids: string[], schedule: Schedule }
```

Readiness checks (in order): store basics, jurisdiction resolved to a LawPack, roles exist,
≥1 employee, every role has ≥1 trained employee, demand exists for every open day,
budget set, no `provisional` constraints older than the current session (warn, not block).

## Chat protocol (Server-Sent Events)

`POST /api/stores/{id}/chat` body: `{mode: "onboard"|"review"|"fix", messages: ChatMessage[]}`
Response is an SSE stream of events:

| event | data | meaning |
|---|---|---|
| `text` | `{delta: string}` | assistant prose, streamed |
| `card` | `{card_id, card_type, props}` | render this card inline; the turn PAUSES until the card is submitted |
| `config` | `{config_version, patch_summary: string[]}` | the config changed (web refetches config + readiness) |
| `tool` | `{name, status: "start"\|"done", summary}` | optional activity line ("Ran dry-run solve") |
| `done` | `{}` | turn complete |
| `error` | `{message}` | |

Card submission: `POST /api/stores/{id}/chat/card` `{card_id, result}` → resumes the same
SSE turn (the result becomes the tool result the LLM sees). `result` may be
`{cancelled: true}`.

`ChatMessage = {role: "user"|"assistant", content: string, card?: {card_id, card_type, props, result}}`
The server keeps the canonical transcript; the client sends only new user messages.

## Card catalogue (card_type → props → result)

| card_type | props | result |
|---|---|---|
| `store_basics` | prefill `Store` fields | `Partial<Store>` |
| `payroll` | prefill `Budget` | `Budget` |
| `roles` | `{departments, roles}` | `{departments, roles}` |
| `training_matrix` | `{employees:[{id,name}], roles}` | `{employee_id: role_id[]}` |
| `coverage_grid` | `{day_type: "weekday"\|"saturday"\|"sunday"\|"truck_day", roles, slot_minutes, prefill: headcount[role][slot]}` | same grid |
| `events` | `{events}` | `{events}` |
| `csv_import` | `{kind, preview?: ImportPreview}` | `{committed: boolean, rows: number}` |
| `propose_rule` | `{constraint: Constraint, evidence, plain_text}` | `{decision: "hard"\|"soft"\|"not_a_rule", weight_dollars?}` |
| `tradeoff` | `{question, options:[{id,label,cost_dollars,effect}]}` | `{option_id}` |
| `conflict_menu` | `{infeasibility: Infeasibility, options:[{id,label,cost_dollars,patch_summary}]}` | `{option_id}` |
| `employee_availability` | `{employee, parsed: AvailabilityEntry[], original_text}` | `{confirmed: AvailabilityEntry[]}` |

## Environment variables

```
OPENROUTER_API_KEY=
AGENT_MODEL=anthropic/claude-sonnet-...     # pick the strongest tool-calling model available on OpenRouter
BASELINE_MODELS=x-ai/grok-...,anthropic/claude-...,openai/gpt-...
MESSENGER=mock            # or twilio
TWILIO_ACCOUNT_SID= TWILIO_AUTH_TOKEN= TWILIO_FROM_NUMBER=
PUBLIC_BASE_URL=          # for the Twilio webhook
DATABASE_URL=sqlite:///./shiftwright.db
```
