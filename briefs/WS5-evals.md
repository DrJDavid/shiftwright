# WS5 — Evals (the proof)

**Folder:** `packages/evals/` (`shiftwright_evals`) · **Oversight:** David
**Read first:** `SPEC.md`, `contracts/models.py`, `briefs/WS2-validator.md`

## Goal
One command (`make eval`) that runs Shiftwright and the general-purpose baselines on the same
scenarios, scores every output with the **validator only**, and writes a report the judges can
believe. Every number traces back to a raw file.

## Systems under test
- `shiftwright`: `shiftwright_engine.solve_week` (and `fix_day`).
- `baseline:<model>` for each model in `BASELINE_MODELS` (Grok + raw Claude and/or GPT via
  OpenRouter). **Fair prompt:** the full `StoreConfig` JSON (including law pack), a plain-English
  explanation of the time conventions, the `Schedule` JSON schema, and the instruction: "Produce
  the lowest-cost schedule that breaks no hard rule. If no such schedule exists, set status
  'infeasible' and explain." Temperature 0, max output tokens as high as the model allows, one
  retry on unparseable JSON. Store the exact prompt in each run folder. Write the prompt to be
  genuinely good; a weak baseline undermines the comparison.
- For large stores, baselines may hit output limits. Record that as an outcome (`truncated`), don't hide it.

## Suites
1. **Weekly build:** S/M/L × easy/tight/legal_trap, 3 seeds each.
2. **Honesty:** 6 `infeasible` scenarios. Score: did the system say infeasible (or flag the
   impossible part) instead of returning a schedule that breaks hard rules?
3. **Call-out repair:** 6 call-out scenarios. Baselines get the schedule, the call-outs, and the
   current time, and must return a revised schedule plus a call list.
4. **Intake (stretch):** feed `narrative` to our onboarding agent (headless mode via the API's
   chat loop with auto-answered cards) vs a baseline asked to extract constraints as JSON. Score
   precision/recall vs `expected.narrative_facts` and whether the contradiction was flagged.

## Metrics (per run, then aggregated)
Valid JSON? · hard violations (total and by code) · coverage % · total cost and **cost vs.
Shiftwright's objective** · budget respected? · infeasibility honesty (TP/FP/FN) · latency ·
for repair: coverage restored and changes before `now` (must be 0).

## Outputs
`runs/<timestamp>/<system>/<scenario>/{prompt.txt, raw_output.txt, schedule.json, validation.json}`
and `reports/<timestamp>/report.html`: a few clear charts (hard violations by system, coverage
vs cost scatter, honesty table, one worked example showing a baseline's specific violations
listed by the validator). Use the dataviz guidance if available; keep it presentable on a projector.

## Cost and time control
Cache baseline responses by hash(prompt, model). Run in parallel with a concurrency limit.
`make eval-quick` = 1 seed, S+M only, for iteration.

## Acceptance tests
- `make eval-quick` runs end to end with `--mock-baselines` (canned bad outputs) and no API key.
- Re-running with the cache produces identical reports.
- Report numbers match a manual recount from `validation.json` files for 2 sampled runs.
