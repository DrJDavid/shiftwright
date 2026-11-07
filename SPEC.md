# Shiftwright — master spec

*Working name. Hackathon theme: "Master of One." Deadline: Saturday Nov 7, ~4:00 pm CT.*

Every agent reads this file first, then `contracts/models.py`, `contracts/API.md`, and its own
brief in `briefs/`. If anything here conflicts with a brief, this file wins; if anything
conflicts with the contracts, the contracts win.

---

## 1. The one thing it does

**Builds the lowest-cost legal weekly schedule for a big-box retail store, and repairs it when
people call out, and every decision can be explained.**

**User:** the store leader responsible for next week's schedule at a big-box store
(departments: Front of Store, General Merchandise, Grocery, Fulfillment, Asset Protection,
Receiving). Corporate sends an hours budget and a coverage forecast; the leader has
discretion for events (trucks, floor sets, online surges) and knows unwritten rules.

**Why a specialist beats a general AI here.** Scheduling is constraint satisfaction. A
general-purpose LLM produces schedules that look right but double-book people, put
untrained staff in roles, blow the hours budget, ignore break and minor-labor law, and
invent a schedule when none is possible. Shiftwright uses an LLM to *understand* the store
and *explain* the schedule, and a CP-SAT solver to *build* it. It cannot produce a schedule
that breaks a hard rule, and it says so plainly when the inputs make full coverage impossible.

## 2. Locked decisions

| Topic | Decision |
|---|---|
| Demo flow | Onboard a store, build the week, then live call-out repair on truck day with real texts. |
| Scale | Configurable. Slot size 15/30/60 min. Evals run S (~25), M (~60), L (~120) staff. Demo store: ~60 staff, 30-min slots. |
| Shifts | The solver creates shifts (any start time on the slot grid, length within rules). No shift templates. |
| Coverage | Soft and priced. Each role has `gap_penalty_per_hour`. A schedule always comes back; gaps are shown with their cost and the reasons. |
| Budget | Corporate **hours** cap is **hard** unless raised by an explicit approval (a `tradeoff` card). Optional dollar cap, also hard. |
| Training | Hard gate. Untrained for a role means never assigned to it. |
| Fairness (v1) | Part-timer minimum hours (soft) and spreading opens, closes and weekends (soft). |
| Unwritten rules | Mapped to `ConstraintKind`s (`not_together`, `fair_spread`, `preferred_role`, ...). Reliability means factual `AttendanceStats`, used **only** to rank call-ins. Anything else goes to `unmodeled` and is shown, never dropped silently. |
| Inferred rules | Mined from past schedules, created `provisional`, and **never used by the solver until confirmed** on a `propose_rule` card. |
| Labor law | A cited dataset of 50 states, federal law, and cities with their own scheduling laws, covering a fixed list of `LawRuleType`s. The LLM never states law from memory. Locations not covered fall back to federal law with a visible warning. |
| Call-out repair levers | Call in off-duty staff, extend or move shifts, reassign roles mid-day, drop low-priority coverage. |
| Outreach | Real SMS through Twilio, behind a `Messenger` interface. A `mock` implementation is the default and stays as the fallback. |
| Baselines | Grok, plus a raw frontier model (Claude and/or GPT) in plain chat with the same inputs, all through OpenRouter. |
| LLM | OpenRouter. Agent model configured with `AGENT_MODEL`; default to the strongest tool-calling Claude model available there. |
| No fine-tune | Agent plus solver plus evals. |
| Deploy | One lightweight service (FastAPI serving the built React app) on Railway or Fly. A public URL is needed for the Twilio webhook. |

## 3. Architecture

```
            ┌──────────────── apps/web (React) ────────────────┐
            │ chat + cards │ rulebook + readiness │ schedule grid │ fixer + SMS inbox │
            └───────────────────────┬──────────────────────────┘
                                    │ REST + SSE (contracts/API.md)
┌──────────────────────── apps/api (FastAPI) ──────────────────────────┐
│ store/config persistence (SQLite) · CSV import · chat agent loop      │
│ (OpenRouter, tools → cards/mutations) · messenger (mock|twilio)       │
└───┬───────────────┬────────────────┬──────────────┬──────────────────┘
    │               │                │              │
packages/engine  packages/validator  data/laws   packages/insights (stretch)
(CP-SAT solve,   (independent rule   (cited law   (mine past schedules →
 fix, explain)    checker)            JSON +       proposed rules)
                                      resolver)
packages/scenarios (seeded synthetic stores, demo store, messy narratives, call-out events)
packages/evals (engine vs baselines; scored ONLY by validator)
```

**Division of labor inside the product:**
- **Solver**: every number and every assignment.
- **Validator**: the single source of truth on whether any schedule (ours or a baseline's) is legal and correct. It shares **no code** with the engine except `contracts/`.
- **LLM**: intake (free text and CSVs into structured config via tools), questions, and putting engine output into plain language. It never computes cost, never writes the config except through tools, and never asserts a reason the engine didn't supply.

## 4. Repo layout and ownership

```
shiftwright/
  SPEC.md                 ← this file (David)
  contracts/              ← David only. models.py, API.md, requests/
  packages/engine/        WS1  (partner oversees)
  packages/validator/     WS2  (David oversees)
  data/laws/              WS3  (David oversees; research agent + verifier agent)
  packages/scenarios/     WS4  (David oversees)
  packages/evals/         WS5  (David oversees)
  apps/api/               WS6  (partner oversees)
  apps/web/               WS7  (David oversees)
  packages/insights/      WS8  stretch (partner, if time)
  briefs/                 per-workstream briefs
  Makefile  pyproject.toml  railway.toml|fly.toml
```

**Stack:** Python 3.12, `uv`, pydantic v2, FastAPI, `ortools`, pytest. Web: React + Vite +
TypeScript + Tailwind. One root `pyproject.toml`; packages are importable as
`shiftwright_engine`, `shiftwright_validator`, etc. (each folder has `src/<pkg>/`).

## 5. Rules for every agent

1. **Stay in your folder.** Edit only your workstream's directory (plus its tests). Need something from another workstream? Use its public function, or put a stub behind the documented interface and note it in your `STATUS.md`.
2. **Never edit `contracts/`.** Write `contracts/requests/<ws>-<topic>.md` and tell David.
3. **Git worktrees.** One worktree and branch per agent: `git worktree add ../sw-<ws> -b ws/<ws>`. Small commits. Rebase on `main` often. Merge to `main` only with tests passing.
4. **Acceptance tests first.** Each brief lists acceptance tests; write them before the implementation.
5. **Keep `<your-folder>/STATUS.md` current**: done, in progress, blocked-on, and any shortcuts taken. David reads these to steer.
6. **Use the demo store fixture** (`packages/scenarios/fixtures/demo_store.json`) once it exists. Until then use `packages/scenarios/fixtures/tiny_store.json` (6 employees, 4 roles, 2 days), which WS4 ships within the first hour.
7. **No invented facts.** No law from memory, no fabricated metrics, no hard-coded "looks good" numbers in the UI.
8. **Timebox.** If something is fighting you for over 45 minutes, write it in STATUS.md and ask.

## 6. Timeline (CT)

| When | Milestone | Done means |
|---|---|---|
| Fri 21:00–22:30 | **M0: Contracts and kickoff** | Spec reviewed, repo scaffolded, contracts frozen at v1, `tiny_store.json` committed, all agents launched. The law research agent starts first since it runs longest. |
| → Sat 02:00 | **M1: Walking skeleton** | Engine solves tiny + demo store; validator passes it; `/solve` works; web shows the schedule grid; chat renders 2 cards (`store_basics`, `payroll`); laws done for TX, CA, and federal. |
| → Sat 09:00 | **M2: Core complete** (agents can run overnight on these briefs) | Full onboarding card set + rulebook + readiness; gap explanations; fix engine; scenario suite S/M/L; eval harness running baselines on ≥10 scenarios; all 50 states drafted. |
| → Sat 13:00 | **M3: Demo complete** | Fixer UI + outreach (mock, then Twilio); deployed; full eval run + report; verifier pass on laws; pattern-mining stretch if possible. |
| **13:00** | **Feature freeze** | Only bug fixes after this. |
| 13:00–15:00 | Hardening | Red-team the unseen challenge (§8), rehearse the demo twice, record a backup video. |
| 15:00–16:00 | Buffer | |

## 7. Demo script (~5 min)

1. **Cold start (60s).** New store "Store #0417, Austin TX". Drop roster, training and corporate-forecast CSVs, confirm the column mappings. The chat asks for the payroll hours cap, the truck schedule, and one unwritten rule ("Jordan and Casey shouldn't close together"), then becomes a `not_together` rule. Pattern cards: "In 8 of 8 weeks you had ≥2 cashiers after 5pm. Rule?" The rulebook fills in, each line with its source; the readiness meter goes green.
2. **Build the week (45s).** Solve. Show the grid, hours vs cap, cost, and coverage %. Click a priced gap: "Fitting room Tue 2–4pm uncovered ($30): the 3 trained people are on the truck unload (higher priority) or at max hours."
3. **The law catch (20s).** A 17-year-old is listed as forklift-trained. The system won't schedule them on PIT and cites the federal hazardous-occupation rule.
4. **Saturday 6:04am (90s).** Three call-outs on truck day. The fixer plan arrives in seconds: one reassignment, one shift extension, and a ranked call-in list. Texting starts and the partner's phone buzzes on stage. He replies "no", the next candidate gets a text and replies "yes", and coverage goes from 71% to 96%. Cost added: $X.
5. **The proof (60s).** Eval chart: hard violations, coverage, cost vs optimum, honesty on infeasible scenarios. Shiftwright vs Grok vs raw Claude/GPT.
6. **Your turn (rest).** The judges try to break it.

## 8. Unseen-challenge playbook (what "earn the trust" looks like)

| Judge throws | Expected behavior |
|---|---|
| A rule that fits a template | Restates it, asks hard or soft (and what it's worth), adds it, shows it in the rulebook. |
| A rule that doesn't fit ("Sam is better with customers") | Says it can't model that, logs it to `unmodeled`, offers the closest supported rule (e.g. `preferred_role`). |
| Contradictory inputs | Names the contradiction, asks which wins. Never picks silently. |
| Impossible demands | Solves anyway with priced gaps. If hard rules conflict, a `conflict_menu` lists the conflicting rules and priced options. |
| "What's the law on X in Ohio?" | Answers only from the dataset, with a citation. If not covered: says so and that federal rules are applied. Not legal advice. |
| Out of scope ("write Bob's performance review", "fire Bob") | Declines briefly and says what it does do. |
| Asked to exceed budget | Only through an explicit approval card that shows the dollar and hour cost. |
| Ambiguous request ("make it cheaper") | Asks what to give up, with priced options. |

## 9. Definition of done (overall)

- Engine schedules for every eval scenario pass the validator with **0 hard violations**.
- Fixer returns a plan for the demo call-out scenario in **under 10 s**; weekly solve for the demo store finishes in **under 30 s**.
- Eval report generated from a single command, with every number traceable to raw run files.
- Every rule in the rulebook shows its source; every law rule shows its citation.
- Deployed URL works end to end with `MESSENGER=mock`; Twilio path tested at least once.
