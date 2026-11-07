# Coordinator handoff

## Update Sat Nov 7, ~01:45 CT (OpenCode coordinator)

- M1 met. Deployed on Railway (Hobby, 8 GB): https://shiftwright-production.up.railway.app/?key=<RAILWAY_DEMO_KEY in .env>.
- Contracts v1.3 (tag `contracts-v1.3`): `Shift.why`, `Store.employer_employee_count`, `Store.schedule_posted_on`,
  SEMANTICS #16 (call-ins ignore preferences) and #17 (predictive-scheduling premiums in fix_day).
- David's decisions: no live phones (mock outreach with scripted replies); demo stores in several localities
  (Austin, Chicago, Seattle, maybe SF) with Fair Workweek premiums priced in repair (fallback at 10:00: Chicago
  without premiums); compliance receipt, per-shift "why", phone-sized employee view; quick real-baseline eval run
  (~$11, cap $42) only after fix_day lands; ~11% proven gap accepted.
- Teammate's research (competitor teardown + "clone and fork" plan): we keep our stack; he owns the pitch,
  "before" slide, demo script, pricing slide, and can design the employee view.
- In flight: WS1 fix_day → Shift.why → #17 premiums → 5-min breaks; WS3 Fair Workweek params/exemptions;
  WS4 locality demo stores; WS6 import safety (forklift tagging of imported roles!) + importer bugs + templates;
  WS7 compliance receipt, why, employee view, locality picker; WS2 engine audit.

## Update Fri Nov 6, 22:50 CT (OpenCode coordinator)

- **Contracts v1.1 on main (`fafe76a`, tag `contracts-v1.1`, pushed).** David accepted all three requests
  (including off-grid breaks at 5-minute granularity) plus WS2's two additions (`Store.school_week`,
  `ViolationCode.below_minimum_wage`). Semantics now live in `contracts/SEMANTICS.md`.
  Known red on main until WS2 lands: `packages/validator` `test_every_code_has_a_golden`.
- `.env`: OpenRouter key set; `AGENT_MODEL=anthropic/claude-sonnet-5.5`; `MESSENGER=mock`.
- Twilio: mock tonight; WS6 adds an allowlist, `X-Demo-Key` header and rate limit; **decide at 10:00 Sat.**
- Evals: mock baselines now; one real 3-model run at M2 (needs coordinator OK).
- Push policy: coordinator pushes `main` after each green merge.
- Claude Code engine session was stopped by David; WS1 continues in OpenCode.
- OpenCode subagents dispatched 22:50 (one per worktree, background): WS1 engine (benchmark the
  two-stage solve, rebase, school_week), WS6 api (outreach test fix, v1.1, hardening, live agent),
  WS2 validator (v1.1), WS7 web (live API default, v1.1, M2 UI), WS5 evals (new, `ws/evals`),
  WS4 scenarios (v1.1, engine verification prep), WS3 laws (state minor limits, primary sources).
- Merge order: WS2 (turns main green) → WS6 (outreach test fix) → WS1 engine → others.

*Written Fri Nov 6, 22:06 CT, by the Claude Code coordinator session, handing off to OpenCode.
Read this, then `SPEC.md`, then `briefs/KICKOFF.md`. Each workstream's `STATUS.md` is the
detailed truth for that workstream; this file is the cross-workstream picture.*

## Where we are

Deadline: Sat Nov 7, ~4:00 pm CT. M1 (walking skeleton) is due **Sat 02:00**; M2 at 09:00; feature freeze 13:00.

`main` contains (all tests green: `uv run pytest` → 306 passed, 3 skipped; `cd apps/web && npm run build` clean):

| WS | What's on main | Next (from its STATUS.md) |
|---|---|---|
| WS4 scenarios | **Brief complete.** `tiny_store.json`, `Scenario` model, `generate(seed,size,difficulty,jurisdiction)`, `demo_store.json` + `demo_scenario.json` (Store #0417 Austin), corporate CSV exports | Once the engine is on main: solve the demo store; confirm the Sat 06:04 call-outs hit real shifts and the demo phones rank 1–2 (re-pick with `pick_callouts()` if not); un-skip the "easy ≥98% coverage" test |
| WS3 laws | Federal, TX, CA (high confidence), 10 city files, OR, all other states + DC drafted from DOL tables (medium), resolver `shiftwright_laws.resolve` | Upgrade DOL-drafted states to primary sources; state minor-hour limits. **Verifier agent starts at M2** |
| WS2 validator | `validate`, `parse_schedule_lenient`, `recompute_metrics`, `validate_raw`; 53 tests incl. golden-bad + fuzz | Run every engine schedule on the S scenarios once the engine lands; file disagreements in its STATUS.md |
| WS6 api | All M1 endpoints, chat SSE + all cards/tools, headless scripted chat, CSV import, fix/outreach/SMS (mock + Twilio), Dockerfile + `apps/api/deploy/railway.toml` | Re-run outreach tests against the real engine; live-agent tests once `OPENROUTER_API_KEY` is set; `/outreach/stream` |
| WS7 web | Three-pane shell, chat with `store_basics`/`payroll`, schedule grid, in-browser mock API seeded from fixtures | M2: remaining cards, rulebook, coverage heatmap, gap explanations, CSV drop. **Flip default to live API** (`src/api/index.ts`) now that WS6 is on main |
| WS1 engine | **NOT merged.** Branch `claude/ws-engine-97a072` (8d6d60c): `solve_week`, `explain_gap`, `find_conflicts` work (tiny store optimal in 0.2 s) | See "Blocked merge" below. Then `fix_day` (M2) and demo-store speed (now ~10% gap at 30 s; target ≤1%) |

Not started yet: **WS5 evals** (can start now: validator + scenarios are on main), **WS3 verifier** (M2), **WS8 insights** (after M2, stretch).

## Blocked merge: WS1 engine

Merging the engine with the API makes 3 tests in `apps/api/tests/test_outreach.py` fail. Cause:
`packages/engine/src/shiftwright_engine/__init__.py` exports a placeholder `fix_day` that imports a
`.fix` module that doesn't exist yet. The API's integration layer sees `fix_day` and assumes the fixer
landed. Fix (engine side): don't export `fix_day` until `fix.py` exists. The WS1 Claude session was
sent this at 22:05; **check the branch for a newer commit before redoing it.** Merge only when the
full root suite (`uv run pytest`, including `apps/api`) passes on the merged result.

## Decisions waiting on David (contracts owner)

Three requests in `contracts/requests/`. Nothing in `contracts/` has been changed yet. Coordinator's recommendations:

1. `ws6-fixplan-plan-id.md`: **accept.** Add `plan_id: Optional[str] = None` to `FixPlan`; document the
   `card_script` body for headless chat and `coverage_grid` props `days`/`start_minute` in `API.md`.
   Bump `CONTRACT_VERSION` to 1.1.0, tag `contracts-v1.1`, run `make types`, tell WS6/WS7/WS5.
2. `ws2-validator-semantics.md`: **accept as written**, and make WS1 match it (notably: coverage is
   0–100; OT premium inside `total_wage_cost`; churn tiebreak kept out of reported metrics, which WS1
   already does). Known benign difference: engine rounds rest-break count half-up, validator uses
   floor; the engine is stricter, so no false violations.
3. `ws1-break-granularity.md`: **decline for now.** Breaks stay on the slot grid (rounded up). Legal,
   costs some paid time on CA stores; Austin demo unaffected.

## How coordination works

- One git worktree + branch per agent. Claude Desktop made them under `.claude/worktrees/<name>`
  (gitignored), on branches `claude/ws-<name>-<suffix>`:
  `ws-scenarios-004300`, `ws-laws-acce23`, `ws-engine-97a072`, `ws-validator-ff6881`, `ws-api-2c0a68`, `ws-web-87b569`.
  For new agents: `git worktree add .claude/worktrees/<name> -b ws/<name> main`.
- Agents commit only on their branch, never push, never merge. They end with
  `READY TO MERGE: <commit> — <what>`.
- Coordinator review per branch: `git log main..<branch>`; `git diff --name-only main...<branch>`
  must stay inside the agent's folder (allowed outside: `uv.lock`, `contracts/requests/*.md`).
  Trial-merge everything in a scratch worktree first (`git worktree add --detach /tmp/trial main`,
  merge, `uv lock && uv sync && uv run pytest`, web build), then `git merge --no-ff` into `main`,
  `uv lock`, re-test. `uv.lock` conflicts: take either side, then `uv lock`.
- After merging, tell the other agents to rebase onto local `main`.
- **Never run two agents in the same worktree.** The Claude Desktop sessions may still be finishing a
  turn (WS1 especially). Before starting an OpenCode agent in a worktree, check `git -C <worktree> status`
  and the branch's latest commit.

### Resuming an agent in OpenCode

```bash
cd .claude/worktrees/ws-engine-97a072 && opencode
```

Prompt: "Read AGENTS.md. You are WS1 (engine). Read your brief in briefs/ and packages/engine/STATUS.md,
rebase onto local main, and continue from STATUS.md's next steps. Follow the commit/merge rules in AGENTS.md."
Swap the WS number, folder, and worktree for the others.

### Launching the next agents

- **WS5 evals (launch now):** worktree `.claude/worktrees/ws-evals`, branch `ws/evals`. Prompt: "Read AGENTS.md.
  You are WS5. Brief: briefs/WS5-evals.md. Import `Scenario`/`generate`/`pick_callouts` from
  `shiftwright_scenarios` and score only with `shiftwright_validator` (`validate_raw` for baseline output).
  The engine isn't on main yet: build the harness with `--mock-baselines` and a shiftwright system that
  imports `solve_week` lazily. `make eval-quick` must run without an API key."
- **WS3 verifier (at M2):** separate worktree. "You are WS3 verifier agent" (see `briefs/WS3-laws.md`).
- **WS8 insights (after M2, if slack):** `briefs/WS8-insights-stretch.md`.

## Human to-dos (David / partner)

- Put keys in `.env` at the repo root (gitignored; worktrees don't see it). Model ids confirmed on
  OpenRouter at 22:00: `AGENT_MODEL=anthropic/claude-opus-5.5` (or `anthropic/claude-sonnet-5.5` if
  chat feels slow); `BASELINE_MODELS=x-ai/grok-4.7,anthropic/claude-opus-5.5,openai/gpt-6.1-terra-pro`.
- Twilio: buy an SMS number, verify both demo phones, **send one test SMS from the Console tonight**
  (US carrier registration can block unregistered numbers; if it fails, demo the mock). Fill
  `TWILIO_*` and `DEMO_PHONE_1/2` in `.env`.
- Railway: generate a public domain (→ `PUBLIC_BASE_URL`). Point the service at
  `apps/api/deploy/railway.toml` (or set the Dockerfile path `apps/api/deploy/Dockerfile`, build from
  repo root). Set the same env vars in Railway. Twilio webhook: `https://<domain>/api/sms/inbound`,
  POST; `PUBLIC_BASE_URL` must match exactly or signature checks reject every reply.
- `main` has not been pushed since the scaffold. Push when ready (`git push origin main`); a linked
  Railway service may auto-deploy on push.

## Before deploying with Twilio live (security)

An automated security review flagged that every `/api/stores/*` route is unauthenticated. On a public
Railway URL, anyone could `PUT` a config with arbitrary phone numbers and call `/outreach/start`,
sending texts billed to the Twilio account. A trial account can only text verified numbers, which limits
the damage but doesn't remove it. Have WS6 add, before Twilio goes live on the deployed URL:
1. An allowlist in `TwilioMessenger`: send only to `DEMO_PHONE_1/2` (or an `SMS_ALLOWLIST` env var);
   anything else is logged and dropped (mock keeps working for everyone).
2. A shared-secret header (e.g. `X-Demo-Key` from env) required on mutating `/api/stores/*` routes;
   `/api/health` and the signature-checked `/api/sms/inbound` stay open.
3. A per-store outreach rate limit.

## Next coordinator actions, in order

1. Merge WS1 once its `fix_day` export fix is in and the full suite passes merged.
2. Decide the three contract requests (above); update contracts, tag, `make types`, notify agents.
3. Launch WS5.
4. M1 check (~01:00–02:00): `make dev`, open the web app with `?api=live`, create a store from the
   demo template, solve, confirm the grid + validator badge show real numbers.
5. Tell WS7 to flip the default to the live API; tell WS4 to verify the demo call-outs against the engine.
