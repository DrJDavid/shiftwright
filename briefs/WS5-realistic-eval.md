# WS5 addendum: the realistic eval ("manager + ChatGPT" vs "manager + Shiftwright")

*Drafted Sat Nov 7 ~01:35 CT by the Claude Code session at David's request. Hand to WS5 via the coordinator.*

## Why

Every number so far gives the baseline models **our** harness: the clean `StoreConfig` JSON, our cited law
pack, and a spec of every hard rule the validator checks. That measures "our solver vs. an LLM used as the
solver inside Shiftwright." It's useful, but it isn't the pitch. A store manager opening ChatGPT has none of
that: they have a description in their head and their corporate CSV exports. This suite compares the two
products starting from the **same raw materials**, scored against the **same ground truth**.

Keep the existing weekly/honesty/repair suites. Rename them in the report to
**"Solver vs. LLM-as-solver (both given Shiftwright's config, law pack and rules)"**.

## New suite: `realistic`

### Inputs (identical for every system)

For each scenario `sc`:
- `sc.narrative`: the store leader's own rambling description (WS4).
- The corporate CSV exports from `shiftwright_scenarios.exports.write_exports(sc, dir)`:
  `roster.csv`, `training.csv`, `availability.csv`, `forecast.csv` (and `history.csv` if the scenario has
  history). Corporate column names, DOB instead of age, job codes, 12-hour times.
- The location as a manager would say it ("We're in Austin, TX").

Nothing else. **No law pack, no rules spec, no StoreConfig JSON, no time conventions, no hint about which
rules exist.**

### Baseline systems: `chat:<model>` for each model in `BASELINE_MODELS`

One user turn, written the way a manager would actually ask, plus the CSVs pasted inline as text (what you'd
get attaching files to a chat):

> I manage a big-box store in {city}, {state}. Here's how the store works: {narrative}
> Attached are my exports from corporate. Can you make next week's schedule (week of {week_start})? Keep me
> under my hours budget, make sure it's legal, and cover the floor as well as you can.
> At the end, give me the final schedule as CSV with columns `TM_ID,Date,Start,End,Job` so I can load it.
> If you have to assume something, just say what you assumed.

- No system prompt beyond the provider default (match what a ChatGPT user gets). Same temperature, max
  tokens, retry-on-unparseable, caching, budget guard and `usage.cost` tracking as the existing suite.
- The CSV-at-the-end request is the only concession to scoring; a real manager would ask for a loadable file too.
- Store the exact prompt and raw reply in the run folder as today.

### Shiftwright system: `shiftwright:intake`

Same inputs, through the real product, headless:
1. `POST /api/stores` with template `empty`, the store name and jurisdiction from the scenario.
2. For each CSV: `POST /import/{kind}` then `/import/{kind}/commit` with the **proposed mapping accepted as
   is** (a manager clicking Confirm).
3. `POST /chat?auto_cards=scripted` in `onboard` mode with the narrative as the first user message. The card
   script must play a neutral manager: **accept every card's prefill/proposal unchanged**; for `propose_rule`
   accept the agent's proposed strength; for `tradeoff` take the first option. **Never feed answers from
   `sc.expected` or `sc.config`.** If `card_script` can't express "accept the prefill", ask WS6 for that
   (small API addition) rather than hand-writing answers.
4. `POST /solve`; take the schedule.

### Scoring: against ground truth, not what each system built

- Map every schedule back to the scenario's true ids: `TM_ID` → employee id (invert
  `exports.tm_id`), job code → role id, date + 12-hour time → `day` + minutes (the mapping tables in the
  `exports` module docstring). A baseline line that doesn't map becomes an `unknown_entity` violation via
  `parse_schedule_lenient`/`validate_raw`, never a crash. Shiftwright's imported ids map the same way.
- Validate every schedule with `shiftwright_validator.validate(sc.config, schedule)`, where `sc.config`
  carries the **true** law pack (`shiftwright_laws.resolve`). So a system that missed a law, an availability
  window, a training gap or the budget during intake is caught exactly as it would be in the real store.
- Metrics as today (0 hard, hard by code, coverage, cost vs Shiftwright, budget, latency, API $), plus:
  - **Intake recall** (Shiftwright only, cheap): fraction of `sc.expected.narrative_facts` present in the
    config the agent built; contradiction flagged yes/no. This is the brief's suite 4.
  - **Stated assumptions** (baselines): count, and whether any assumption contradicts the CSVs.

### Scenarios (quick set)

1. Demo-like M normal, TX (Austin).
2. S `legal_trap`, CA (minor PIT-trained, meal/rest breaks, clopen-prone availability).
3. M `tight`, TX (budget below need: does the system respect the cap or quietly blow it?).
4. A `food` scenario (Chicago) once WS4 ships one (tipped servers, fryer minor).

One seed each to start. Mock mode first (`--mock-baselines`, canned replies covering: perfect, wrong ids,
no breaks, over budget, unparseable), and the full Shiftwright path must run with **no API key** using the
API's fake LLM so CI stays green.

### Spend

Prompts are smaller than the current suite (CSVs + narrative instead of full config + law pack). Run
`shiftwright_evals.estimate` for the suite and **get the coordinator's/David's OK before any real call**.
Expect single-digit dollars for the quick set.

### Report

- **Headline chart (first in the report): "From the same raw inputs"**: hard violations and legal coverage
  per system, plus minutes per schedule. This is the chart for the pitch.
- Second section: the existing suites under their new name.
- One worked example: a baseline's specific violations listed by the validator next to what Shiftwright did
  with the same input (e.g. the 17-year-old on the forklift, a missed CA meal break, an unavailable shift).
- Limitations box, stated plainly: one turn, no follow-up questions; consumer ChatGPT may use browsing or code
  tools the API run doesn't; small sample. Don't hide it.

## Done means

`make eval-quick` includes `realistic` in mock mode with no key; one real quick run approved and in
`STATUS.md` with spend; report headline is the same-inputs chart; every number traces to raw files.
