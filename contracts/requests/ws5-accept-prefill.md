# WS5 request: headless chat mode "accept every card's prefill"

**From:** WS5 (evals), Sat Nov 7 ~02:00 CT. **For:** WS6 (API) / David (API.md).

## What
A headless chat mode in which every card is answered with its own proposal, unchanged, e.g.
`POST /api/stores/{id}/chat?auto_cards=accept_prefill` (no `card_script` needed).

## Why
The realistic eval (briefs/WS5-realistic-eval.md) plays a neutral manager who clicks Confirm on every
card. `card_script` answers by card type with fixed results, so it can't echo each card's props back,
and hand-writing answers would leak the scenario's ground truth.

## Proposed semantics (what WS5 implements today as a stand-in)
`shiftwright_evals.realistic.accept_prefill(card_type, props)`:

| card_type | result |
|---|---|
| store_basics, payroll | props minus `id` / `approvals` |
| roles | `{departments, roles}` from props |
| training_matrix | `{employee_id: trained_role_ids}` from props |
| coverage_grid | `{prefill: props.prefill}` |
| department_staffing | `{staffing: props.suggested}` |
| events | `{events: props.events}` |
| csv_import | `{committed: false, rows: 0}` (CSV already imported over REST) |
| propose_rule | `{decision: constraint.strength}` (+ its `weight_dollars` when soft) |
| tradeoff, conflict_menu | first option |
| employee_availability | `{confirmed: props.parsed}` |
| anything else | `{cancelled: true}` |

Until the API supports it, WS5 patches `shiftwright_api.main.scripted_waiter` in its own process
when `card_script` contains the key `__accept_prefill__` (no change to apps/api). Once the mode
exists, WS5 switches to it and drops the patch.

## Related finding (WS6)
With the proposed mappings accepted as is and no helper LLM, `forecast.csv` is rejected:
`Req HC` is not proposed for `headcount` ("Required fields not mapped: ['headcount']"), so the store
gets no demand from the corporate forecast. Suggest adding `req hc` / `req. hc` / `required headcount`
to the heuristic synonyms.
