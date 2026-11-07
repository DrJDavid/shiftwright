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
- Tests (13, `uv run pytest packages/evals`, ~2 s): the 3 brief acceptance tests (CLI subprocess with no key;
  cached re-run identical; 2 sampled runs recounted from validation.json against report.json and the HTML row)
  plus OpenRouter request shape/retry/cache/truncation/HTTP error via `httpx.MockTransport`, prompt completeness,
  mock kinds → intended validator codes.

**Shiftwright on main (4f53a85), `make eval-mock`, quick, 30 s limit (Fri 23:15):**

| Scenario | Status | Hard | Coverage | Objective $ | Latency |
|---|---|---|---|---|---|
| weekly S easy | feasible | 0 | 98.0% | 12,966.62 | 26 s |
| weekly S tight | feasible | 0 | 89.5% | 13,992.75 | 26 s |
| weekly S legal_trap (CA) | **infeasible** (`conflicting_other=["solver_timeout"]`) | 7 (always_staffed, no shifts) | 0% | – | 42–49 s |
| weekly M easy | feasible | 0 | 93.2% | 29,246.88 | 27 s |
| weekly M tight | feasible | 0 | 89.2% | 30,309.25 | 27 s |
| weekly M legal_trap (CA) | **error** ("No schedule found within the time limit") | 7 | 0% | – | 28 s |
| honesty S / M infeasible | infeasible, named the right ids | – | – | – | 13 s / 14–26 s |
| repair S / M | unavailable (no `fix_day` yet); base schedule = engine solve_week | | | | |

4/6 weekly pass with 0 hard violations; honesty 2/2 correct + conflict named; but the engine reports a
*timeout* as `status="infeasible"`, which the honesty score counts as a false "infeasible" (FP) on S legal_trap.
Both CA legal_trap stores fail: passed to WS1. Coverage figures differ slightly run to run (CP-SAT time limit).
L easy (120 staff) standalone: 30 s → 93.2% / 0 hard; 60 s → 95.3% / 0 hard.

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
