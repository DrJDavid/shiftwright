# WS6 request: an id for FixPlan (and two small API.md clarifications)

**From:** WS6 (api) · **Status:** open · **Blocking:** no (workaround in place)

## 1. `plan_id` for `/fix` → `/outreach/start`
`POST /api/stores/{id}/fix` returns `FixPlan`, but `POST /outreach/start` takes `{plan_id}` and
`FixPlan` has no id field.

**Workaround now:** the API returns the `FixPlan` JSON plus a top-level `"plan_id"` key. It still validates
as `FixPlan` (pydantic ignores extras), but the generated TS type won't have it.

**Ask:** either add `plan_id: Optional[str] = None` to `FixPlan` (engine leaves it None; API fills it),
or document in API.md that `/fix` returns `FixPlan & {plan_id: string}`.

## 2. Headless chat script (document only)
`POST /chat?auto_cards=scripted` needs the scripted answers somewhere. WS6 reads them from the request
body: `card_script: {card_type: [result, ...]}` (consumed in order; no answer left → `{cancelled: true}`).
Please add that to the chat section of API.md so WS5 can rely on it.

## 3. `coverage_grid` props (document only)
`prefill: headcount[role][slot]` doesn't say where slot 0 starts or which days the day_type covers.
WS6 adds `days: int[]` and `start_minute: int` to the props (slot i = [start_minute + i*slot_minutes, +slot)).
Please add them to the card catalogue so WS7 renders the right time axis.


---
**Decision (David, Fri Nov 6 22:30 CT): ACCEPTED in contracts v1.1.** See `contracts/SEMANTICS.md`.
