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
- Tests (11, `uv run pytest packages/evals`, ~2 s): the 3 brief acceptance tests (CLI subprocess with no key;
  cached re-run identical; 2 sampled runs recounted from validation.json against report.json and the HTML row)
  plus OpenRouter request shape/retry/cache/truncation/HTTP error via `httpx.MockTransport`, prompt completeness,
  mock kinds → intended validator codes.

**Trial against the engine (not merged; branch `claude/ws-engine-97a072` @ 6cb51b9 via PYTHONPATH, quick, 30 s limit):**
251 s wall. Engine: S easy/tight and M easy pass (0 hard), coverage 76% / 82% / 62%; S legal_trap (CA), M tight,
M legal_trap returned `status="error"` with no shifts (no solution in 30 s); both infeasible stores → `infeasible`
naming the right conflict ids. No `fix_day` yet → repair rows unavailable; repair base fell back to history on M
(engine returned no shifts). Worth passing to WS1.

**Next:**
- When the engine lands on main: full run `uv run python -m shiftwright_evals --engine-workers 2` (est. 39 + 6
  solves × ~26 s ≈ 10–20 min). When `fix_day` lands the repair suite picks it up automatically.
- At M2 (once authorized): `BASELINE_MODELS=x-ai/grok-4.7,anthropic/claude-opus-5.5,openai/gpt-6.1-terra-pro`
  with `OPENROUTER_API_KEY` set; start with `--quick` to check cost/time. L prompts are ~100 kB of config JSON.
- Intake suite (stretch): headless chat via API `auto_cards=scripted` vs baseline JSON extraction.

**Blocked on:** nothing.

**Shortcuts taken / notes:**
- Without the engine, the repair base schedule is the scenario's last history week re-dated (greedy, has its own
  violations); the report says which base was used.
- Engine `status="error"` (no solution in time) is scored as a failed schedule and honesty `no_answer`.
- Root `make eval-quick` doesn't pass `--mock-baselines` (Makefile is outside this folder); coordinator may want
  a `make eval-mock` target.
- Honesty "named the conflict" = id overlap only (not free-text matching of the summary).
