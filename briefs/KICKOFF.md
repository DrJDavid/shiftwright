# Kickoff runbook (for David)

## 0. Before launching anyone (~30 min, you + partner)
1. Read `SPEC.md` §2 together; change anything you disagree with *now*.
2. Scaffold: `git init`, root `pyproject.toml` (uv workspace; deps: pydantic, fastapi, uvicorn,
   ortools, httpx, pytest), `contracts/` as package `shiftwright_contracts`, empty package
   folders each with `src/<pkg>/__init__.py`, `tests/`, `STATUS.md`. `apps/web` via
   `npm create vite@latest web -- --template react-ts`. Makefile targets: `test`, `types`
   (JSON Schema → TS), `eval`, `eval-quick`, `dev`.
3. Commit to `main`. Tag `contracts-v1`.

## 1. Launch order
| # | Agent | Worktree | Prompt |
|---|---|---|---|
| 1 | WS4 scenarios | `../sw-scenarios` | "Read CLAUDE.md. You are WS4. Ship `fixtures/tiny_store.json` first, commit it to main, then continue your brief." |
| 2 | WS3 law research | `../sw-laws` | "Read CLAUDE.md. You are WS3 research agent. Work through your brief; commit per state." |
| 3 | WS1 engine | `../sw-engine` | "Read CLAUDE.md. You are WS1." |
| 4 | WS2 validator | `../sw-validator` | "Read CLAUDE.md. You are WS2. Do not read packages/engine." |
| 5 | WS6 api/agent | `../sw-api` | "Read CLAUDE.md. You are WS6. Stub engine/validator calls behind their documented interfaces until they land." |
| 6 | WS7 web | `../sw-web` | "Read CLAUDE.md. You are WS7. Use a mock server from contracts until WS6 lands." |
| 7 | WS5 evals | `../sw-evals` | Start at M1 (needs validator + scenarios). |
| 8 | WS3 verifier | `../sw-laws-verify` | Start at M2. "You are WS3 verifier agent." |
| 9 | WS8 insights | `../sw-insights` | Only after M2, if there's slack. |

## 2. Shepherding loop (every ~45–60 min)
- Read each `STATUS.md`. Unblock contract requests fast (merge, bump the minor version, tell the dependent agents to rebase).
- Merge green branches into `main`; have agents rebase.
- At each milestone, run the full stack yourself against `demo_store.json`.
- Disagreements between engine and validator: you decide who's right from the contracts.

## 3. Things only humans can do
- OpenRouter key and model choice (pick `AGENT_MODEL`; confirm Grok and Claude/GPT ids for `BASELINE_MODELS`).
- Twilio: account, number, verify the two demo phones (trial accounts can only text verified numbers). Decide by **10:00 Sat** whether Twilio is live; otherwise demo the mock.
- Railway/Fly account + deploy secrets.
- Sanity-check the demo store against what a real store looks like (your Target experience).
- Rehearse the demo; record the backup video.
