# Prompt for the Cursor coordinator (paste as-is)

You are the **coordinator** for the Shiftwright repo (`~/Development/shiftwright`). Read `AGENTS.md`, then
`PUNCHLIST.md` top to bottom (it changed at 05:25: new merge rules, a status board, and task C3).

**Merge rules (these replace anything earlier):**
1. You are the **only** agent that commits to `main`, merges, or pushes. Every worker, including the
   Claude Code session, works only on its own branch (`cursor/<task-id>` or `claude/<task-id>`), never on
   `main`, and never pushes. If you see a commit on `main` that you didn't make, stop and tell David.
2. Nobody but you edits files in the main checkout's working tree. Workers use their own worktrees.
3. Before each merge: trial-merge in a scratch worktree from current `main`; run `uv lock && uv sync &&
   uv run pytest`, then `cd apps/web && npm install && npm run build && npm run lint && npm test`. Merge with
   `--no-ff` only when everything is green. Then push `main`, tell the other workers to rebase, and update
   the status board in `PUNCHLIST.md`. Never force-push; never rewrite `main`'s history.
4. A worker's branch may only touch the files its task lists (plus `uv.lock` and
   `contracts/requests/*.md`). Anything else: send it back.
5. No paid LLM calls from agents, tests or scripts. The only exception is task E3, and only after David
   says yes in chat with the estimate in front of him.

**What changed on `main` recently (make sure workers rebase onto it):**
- `80e21fc` (Claude Code): chat setup saves every stated fact immediately (hours format, roles before
  people, each person once); phone is optional (outreach skips people without one); new readiness check
  for priorities below pay; `make dev-api` reloads only on app source.
- `7304274` (Claude Code): role priorities in plain words. Managers pick **Must cover / Important / Nice to
  have**; `apps/api/src/shiftwright_api/priorities.py` prices levels from wages; the roles card shows a
  priority picker; gap explanations say "priority: Nice to have". Levels live in the API kv store.
- `95bd2c1`, `30ebd07`, `2dcc332`: you merged D1, E1, C1 (+C2 split shifts).

**Next, in this order:**
1. Bring the open branches up to date with `main` and merge the green ones: A1 auth, A3 generated
   businesses, B1 web shell, E2 rescore, E4 dataset builder. A1 and A3 touch `apps/api/src/shiftwright_api/main.py`
   near the `/gaps/explain` handler, which now passes priority levels to `phrase_gap`; keep that line.
2. Start **C3 (coverage first, then cost)**. David decided money must never decide whether an hour gets
   covered. Hard deadline 10:00 CT: if it isn't green on all demo stores by then, leave it on its branch
   and keep the current behavior for the demo. C3b (API) and C3c (evals) follow once C3 lands.
3. Lane B: B2 → B4 → B7, including the two QA bugs listed under B4: the first-visit store must start from
   template `empty`, and Build stays disabled until people, training and staffing exist (no "Coverage 100%"
   on an empty week).
4. A2, B3, B5, B6, then E3 only with David's OK.

**From 11:00:** no new features. Only fixes for whatever breaks the demo rehearsal on the deployed URL.
Freeze at 13:00.

Report to David after each merge in one line: what merged, test totals, what's next.
