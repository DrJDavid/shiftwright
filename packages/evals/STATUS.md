# WS5 status: evals

**Done (harness, tested with mock baselines only):**
- `python -m shiftwright_evals [--quick] [--mock-baselines] [--suites weekly,honesty,repair] [--no-engine]
  [--engine-time-limit 30] [--engine-workers 1] [--concurrency 4] [--models a,b] [--no-cache] [--run-id X]`.
  `make eval-quick` = `--quick` (real baselines only if `OPENROUTER_API_KEY` *and* `BASELINE_MODELS` are set,
  otherwise baselines are skipped with a note). For the mock end-to-end run use
  `uv run python -m shiftwright_evals --quick --mock-baselines`.
- Suites (`suites.py`): weekly = S/M/L × easy/tight/legal_trap × seeds 1–3 (legal_trap in CA, others TX) = 27;
  honesty = S/M/L infeasible × seeds 1–2 = 6; repair = S/M normal × seeds 1–3 = 6. `--quick`: 1 seed, S+M
  → 6 + 2 + 2 = **10 scenarios**. Intake: stub (report says "not implemented").
- Systems (`systems.py`): `shiftwright` (lazy `import shiftwright_engine`; `solve_week`, `fix_day` if exported;
  otherwise rows are `unavailable` with the reason) and `baseline:<model>` (OpenRouter, temperature 0,
  max_tokens from `/models` `top_provider.max_completion_tokens`, one retry on unparseable JSON, no retry on
  `finish_reason=length` → outcome `truncated`; HTTP errors → outcome `error`, never cached).
- Prompt (`prompts.py`): brief's instruction verbatim, time conventions, every hard rule the validator checks
  (pointing at config fields; law only from `config.law_pack`), objective, output rules, the `Schedule` JSON
  schema, and the full `StoreConfig` JSON. Repair prompt adds the current schedule, call-outs, `now`, levers,
  and asks for `{"schedule", "call_list"}`. Exact messages saved in `prompt.txt`.
- Cache: LLM replies by sha256(model, messages) in `packages/evals/.cache/llm*/`; engine outputs by
  sha256(engine source hash, call, inputs) in `.cache/engine/`. Re-runs are byte-identical apart from the run id.
- Output: `runs/<id>/<system>/<scenario>/{prompt.txt, raw_output.txt, schedule.json, validation.json, run.json
  [, call_list.json, raw_output.attempt1.txt]}`, `runs/<id>/_inputs/<scenario>/` (config with law pack,
  expected, repair base schedule + call-outs), `runs/<id>/manifest.json`, `reports/<id>/{report.html, report.json}`.
  `runs/`, `reports/`, `.cache/` are gitignored (`packages/evals/.gitignore`).
- Scoring (`score.py`) reads only the run folder. Per run: outcome, hard count + by code, coverage, wage cost,
  objective, hours vs cap, budget respected, said-infeasible, named the conflict (overlap with
  `expected.conflicting_ids`), honesty TP/FN/FP/TN/no_answer, cost vs Shiftwright (objective ratio, only
  against an engine schedule that passed), latency; repair: coverage before (call-outs removed) → after,
  changes before `now` (employees other than the callers), called-out staff still scheduled, call-list size and unknown ids.
- Report (`report.py`): mock banner, pass-rate bars, violations-by-rule stacked bars, summary table, legal-coverage
  bars, coverage vs hours-cap scatter (hollow = hard violations), honesty table, repair table, worked example
  (baseline weekly run with the most distinct violation codes, validator messages), all-runs table with links.
- Mocks (`mock.py`, `baseline:mock-a`, `baseline:mock-b`): read the config from the prompt, sloppy greedy schedule +
  one of hallucinated_employee / minor_on_forklift / over_budget / truncated / unparseable / sloppy /
  claims_infeasible; never detect infeasibility (false "feasible"). Repair: ignored_callout / changed_past / careful.
- Tests (20, `uv run pytest packages/evals`, ~2 s): the 3 brief acceptance tests (CLI subprocess with no key;
  cached re-run identical; 2 sampled runs recounted from validation.json against report.json and the HTML row)
  plus OpenRouter request shape/retry/cache/truncation/HTTP error via `httpx.MockTransport`, prompt completeness,
  mock kinds → intended validator codes.

**Realistic suite (briefs/WS5-realistic-eval.md), slice 7, Sat Nov 7 ~02:00 CT. Mock mode done; no real calls yet.**
- `shiftwright_evals/realistic.py`; in the default suites (`weekly,honesty,repair,realistic`), so `make eval-quick`
  and `make eval-mock` include it.
- Inputs per scenario: `sc.narrative` + `write_exports` CSVs (roster, training, availability, forecast, history) +
  location. Quick set: M normal TX/austin, S legal_trap CA, M tight TX, food M normal IL/chicago (**skipped today:
  `write_exports` raises KeyError 'management' for the food store → WS4**; the run notes it and continues).
- `chat:<model>`: one user message, no system prompt, the brief's wording, CSVs pasted as fenced `name.csv:` blocks;
  one retry if no loadable CSV; same cache / budget guard / usage.cost as the solver suite. The CSV reply is mapped to
  true ids (TM_ID → employee via `exports.tm_id`, job code → role via `JOB_CODES`, MM/DD/YYYY or ISO date → day,
  12-h or 24-h times; end ≤ start = overnight). Consecutive lines of one person on one day with a gap ≤ 60 min form
  one shift with a break (< 30 min paid rest, ≥ 30 min unpaid meal). Unmappable ids stay as given → `unknown_entity`.
  `mapping.json` per run: rows, bad rows, stated-assumption count (heuristic; contradiction check not scored).
- `shiftwright:intake`: the real API in-process (`create_app` + TestClient, temp SQLite per store): `POST /api/stores`
  template `empty`, `/import/{kind}` + `/commit` with `proposed_mapping` as is, `/chat?auto_cards=scripted` onboard
  with the narrative (up to 4 turns with a neutral "please keep going" when the real agent leaves readiness red),
  `/solve` at the engine time limit. Card answers = `accept_prefill(card_type, props)`; the API has no such mode yet,
  so WS5 patches `main.scripted_waiter` in-process when `card_script` has `__accept_prefill__`
  (**request filed: `contracts/requests/ws5-accept-prefill.md`**). Output ids mapped back like the baselines;
  `built_config.json`, `intake_log.json` (imports, cards, readiness), `intake_recall.json` (narrative facts present /
  checked; peaks unchecked). Without a key the agent is the API's `FakeLLM` scripted to open store_basics + payroll
  and accept them; it never reads the narrative (report banner says so). Real agent only when real baselines run.
- Findings already: with heuristic mapping (no helper LLM) `forecast.csv` is rejected (`Req HC` not mapped to
  `headcount`) → Shiftwright gets no demand from the forecast (→ WS6, in the request file).
- Report: "From the same raw inputs" is now the first section (pass rate, violations by rule, legal coverage, minutes
  per schedule with cost, table with intake recall / assumptions, worked example, limitations box); the old suites
  follow under "Solver vs. LLM-as-solver (both given Shiftwright's config, law pack and rules)".
- Estimate (`uv run python -m shiftwright_evals.estimate --quick --suite realistic`, live prices): prompts ≈ 19k
  tokens (S) / 45k (M). Chat at the tool's default (answer CSV + 2× reasoning): grok $0.45, opus $1.22, gpt $0.30.
  Calibrated with real-quick-1's measured completion tokens (grok ≈ 89k, opus ≈ 46k, gpt ≈ 30k per reply):
  ≈ $1.8 + $3.2 + $0.6 = **≈ $5.6 for chat**. Intake agent (sonnet-5.5, assumed 30 calls × 25k prompt + 800 out per
  store, not measured): **≈ $5.2**. **Total ≈ $7–11; ceiling ≈ $20** (chat capped at 128k output tokens; the agent's
  spend goes through the API's own client, so the harness budget guard does not see it; MAX_TURNS = 4 bounds it).

**Engine at 120 s + re-scored baselines: `rescore-120`, Sat Nov 7 ~01:10 CT, main 41111c1 (no new spend).**
`uv run python -m shiftwright_evals --quick --rescore-from real-quick-1 --run-id rescore-120` (engine defaults now
`S=120,M=120,L=120`, 2 workers; 357 s wall). Baseline rows = real-quick-1 replies re-validated against today's scenarios,
matched by scenario id + model (`ReplaySystem`); 0 API calls; all 30 reusable (config diffs are only new v1.5 fields:
contract_version, events.label, roles.tipped, store.business_description, store.max_shifts_per_day). Call-out inputs
(base schedule + call-outs) are reused so fix_day and the baselines repair the same schedule.
Report: `packages/evals/reports/rescore-120/report.html`.

| Weekly build (6) | 0 hard | Hard | Median legal coverage | Cost vs SW | Median time / schedule | API $ |
|---|---|---|---|---|---|---|
| Shiftwright (120 s) | 4/6 | 8 (7 always_staffed: "infeasible" on S legal_trap CA; 1 below_minimum_wage) | 91.8% | 1.00× | 116 s | – |
| grok-4.7 | 5/6 | 2 | 90.0% | 1.01× | 1,299 s | 4.62 |
| claude-opus-5.5 | 4/6 | 4 | 92.8% | 0.99× | 425 s | 9.38 |
| gpt-6.1-terra-pro | 2/6 | 14 | 91.1% | 1.03× | 216 s | 1.81 |

At 120 s the cost gap is gone (was 0.94–0.95× at 30 s). Honesty 2/2 for everyone; repair: Shiftwright 2/2 clean
in 0.7–1.9 s. Caveat: the validator doesn't check `shifts_per_day` (SEMANTICS #23) yet; when WS2 adds it, Grok's
clean S legal_trap schedule (one split day) fails under max_shifts_per_day=1 until WS4 sets 2 for that store.

**Next (waiting on WS1 split shifts + quality, WS4 legal_trap CA max_shifts_per_day=2 + no min-wage trap + food scenarios):**
real-quick-2 = `--quick --rescore-from real-quick-1 --run-id real-quick-2` (re-scoring stays valid while the
store's employee/role ids, demand, hours and week are unchanged; otherwise those rows are listed under "Not
re-scored" and need coordinator approval for new spend). Then drop `SUSPECT_EXPECTED` for S legal_trap CA, and add
food scenarios to `build_cases(quick=True)` once `generate` supports them (food rows will have no cached baseline
replies → they need a new prompt, ask first).

**First real baseline run (approved by David): `real-quick-1`, Sat Nov 7 ~00:00–00:35 CT, main 0414a9b.**
`--quick --max-output-tokens 128000 --concurrency 8 --budget-usd 42`. 30 OpenRouter calls, 0 retries, 0 truncated,
**actual spend $15.81** (grok $4.62, opus $9.38, gpt $1.81; from `usage.cost`), wall 2,014 s (Grok is the long pole).
Report: `packages/evals/reports/real-quick-1/report.html` (rebuild: `python -m shiftwright_evals --report-only real-quick-1`).
Responses are cached in `packages/evals/.cache/llm/` (gitignored); re-runs cost $0.

| Weekly build (6) | 0 hard | Hard total | Median legal coverage | Median cost vs SW (both legal) | Median latency |
|---|---|---|---|---|---|
| Shiftwright | 4/6 | 8 (7 = empty "infeasible" on S legal_trap CA; 1 below_minimum_wage) | 91.3% | 1.00 | 26.5 s |
| grok-4.7 | 5/6 | 2 (not_trained, unavailable) | 90.0% | **0.95** | 1,299 s |
| claude-opus-5.5 | 4/6 | 4 (3 not_trained, 1 below_minimum_wage) | 92.8% | **0.94** | 425 s |
| gpt-6.1-terra-pro | 2/6 | 14 (7 meal_break, not_trained, unavailable, 2 budget_hours) | 91.1% | 0.98 | 216 s |

Honesty: every system said infeasible on both impossible stores and named the right conflict (2/2); no system
said infeasible on a feasible weekly store. Repair (fix_day now live): Shiftwright 2/2 clean, optimal, ~1 s,
coverage 92.3→93.9% (M) and 91.6→94.2% (S), 5–7 call-ins. Baselines: S repairs clean (63–700 s); M repairs:
grok and opus 6 hard (4 malformed segments + shift_length), gpt returned "infeasible" with no shifts (47 employees'
past assignments wiped).

**Findings for the coordinator (not harness bugs):**
1. **Engine cost is not optimal at 30 s:** on every scenario where both pass, Grok and Opus schedules cost 5–7% less
   (validator-recomputed objective), sometimes with higher coverage (Opus S easy: 100% / $12,210.75 vs engine 95.7% /
   $13,084.62). → WS1: longer limit, better warm start, or report the bound.
2. **`weekly-S-legal_trap-CA-s1` is feasible after all:** Grok returned a validator-clean schedule (0 hard, 90.7%
   coverage) with 21 leader shifts: overlapping hand-offs with 10-min rest breaks timed inside the overlap, shifts
   ≤ 6 h so meals are waived, and one split day (e002 Sun 08–12 + 18–22) to stay within 5 days. The engine's
   "proof" holds only under its own shift model (fixed break placement, one shift per day). The report still marks
   the scenario suspect, as instructed, and says a baseline passed it.
3. **CA legal_trap wages below CA minimum wage** (e013/e053 at $15.75 vs $16.90): `below_minimum_wage` fails the
   engine on M and Opus on S. → WS4 scenario data (or intended as a trap; then the engine should avoid scheduling them?
   SEMANTICS #15 says the engine schedules as normal, so this will always fail the engine).

**Full-run wall time (`make eval`, defaults now `--engine-workers 2`, `--engine-time-limit S=30,M=30,L=60`):**
- Measured: quick engine part 276 s with 1 worker, 134 s with 2 (per-solve latency unchanged; 14-core Mac).
- Full = 39 solves (27 weekly + 6 honesty + 6 repair bases; 11 are L) ≈ 28×27 s + 11×55 s ≈ 1,360 s of solving
  → **≈ 11–12 min with 2 workers** (≈ 8 min with 3), + ≤ 6×10 s for `fix_day` once it lands. Cached re-runs: seconds.
- Real baselines (not measured, no calls made): 3 models × 10 quick scenarios = 30 calls; reasoning-model replies of
  20–90k tokens likely take 2–10 min each. With `--concurrency 8`: **≈ 15–30 min for quick**; full (117 calls)
  ≈ 1–1.5 h at concurrency 8. Everything is cached, so an interrupted run resumes for free.

**OpenRouter cost estimate** (`uv run python -m shiftwright_evals.estimate [--quick]`; prices fetched live from
`/api/v1/models` Fri 23:20; tokens = actual prompt chars / 3; answer = a full schedule's compact JSON; reasoning
tokens assumed 2× the answer):

| Model | $/Mtok in / out | Max output | Quick (10 scen.) typical | Full (39) typical |
|---|---|---|---|---|
| x-ai/grok-4.7 | 2 / 6 | 450k | $2.23 | $12.56 |
| anthropic/claude-opus-5.5 | 4 / 20 | 128k | $6.82 | $38.98 |
| openai/gpt-6.1-terra-pro | 1 / 5 | 128k | $1.71 | $9.74 |
| **Total** | | | **≈ $11** | **≈ $61** |

Prompt sizes: S ≈ 22k tokens, M ≈ 40k, L ≈ 42k (config JSON incl. law pack). Answers: S ≈ 6k, M ≈ 15k, L ≈ 27k.
Worst case (every reply runs to its max output, plus input): quick ≈ $60 (grok's 450k limit is most of it);
with `--max-output-tokens 128000` the quick ceiling is ≈ $42 and the full ceiling ≈ $163. One retry on
unparseable JSON can add up to one more call per run. **Recommendation:** approve the quick run (≈ $11 expected,
≤ $42 hard ceiling with `--max-output-tokens 128000 --concurrency 8`).

**Blocked on:** nothing.

**Harness additions (slice 5):** `--rescore-from RUN_ID` (ReplaySystem; per-scenario `config_changes.json`; blocking
if employee/role ids, demand, hours, week or store id changed), engine default 120 s, "Minutes per weekly schedule,
with schedule cost" chart, median + total time next to cost in the summary table, mock kinds keyed on store id.

**Harness additions (slice 4):** `--budget-usd` guard (stops new paid calls when spend + average-cost
projection exceeds it; spend from OpenRouter `usage.cost`, requested with `usage: {include: true}`), per-run
`cost_usd` in the report, `SUSPECT_EXPECTED` in `suites.py` (honesty label `suspect` instead of FP), `--report-only`,
request timeout 40 min, chart labels use the model name after the slash.

**Report:** the worked example is now a side-by-side: one baseline vs Shiftwright on the same weekly scenario
(prefers scenarios Shiftwright passed and a baseline that put a minor on a prohibited role), metrics table, the
baseline's violations by rule with validator messages and law-rule ids, and Shiftwright's validator result.

**Shortcuts taken / notes:**
- Without the engine, the repair base schedule is the scenario's last history week re-dated (greedy, has its own
  violations); the report says which base was used.
- Engine `status="error"` (no solution in time) is scored as a failed schedule and honesty `no_answer`.
- Root `make eval-quick` doesn't pass `--mock-baselines` (Makefile is outside this folder); coordinator may want
  a `make eval-mock` target.
- Honesty "named the conflict" = id overlap only (not free-text matching of the summary).
