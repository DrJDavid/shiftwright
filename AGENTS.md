# Instructions for every coding agent in this repo

1. Read `SPEC.md` (especially §5, "Rules for every agent"), then `contracts/models.py`,
   `contracts/API.md`, then your brief in `briefs/`.
2. Work only inside your workstream's folder, in your own git worktree/branch.
3. Never edit `contracts/`. Request changes in `contracts/requests/`.
4. Write the acceptance tests from your brief first. Keep `<your-folder>/STATUS.md` current.
5. Never invent labor law, metrics, or reasons. Numbers come from the engine/validator; law comes from `data/laws`.
6. If blocked for over 45 minutes, write it in STATUS.md and stop to ask.

## Coordination (for the coordinator and every agent)

- Coordinator: read `HANDOFF.md` first; it holds cross-workstream state, open decisions, and next actions.
- Agents: commit only on your own branch, in your own worktree. Never push, never merge into `main`.
  When a slice is ready and the full suite passes, end with `READY TO MERGE: <commit> — <what>`.
- Add Python deps only to your package's `pyproject.toml` (then `uv sync`); `uv.lock` conflicts are expected.
- Keep your `STATUS.md` current enough that a fresh agent could continue from it alone.
