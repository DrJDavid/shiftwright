# Shiftwright

Constraint-solved retail scheduling with a plain-language front end. Read [`SPEC.md`](SPEC.md) first, then [`CLAUDE.md`](CLAUDE.md) and your brief in [`briefs/`](briefs/).

## Setup

Needs [`uv`](https://docs.astral.sh/uv/) and Node 20+.

```bash
make install        # uv sync (Python 3.12 workspace) + npm install for apps/web
cp .env.example .env
make test           # pytest across every package
make dev            # API on :8000, web on :5173 (proxies /api)
```

Other targets: `make types` (contracts → `apps/web/src/contracts.ts`), `make eval`, `make eval-quick`.

## Layout

| Path | Workstream | Python package |
|---|---|---|
| `contracts/` | David only (change requests go in `contracts/requests/`) | `shiftwright_contracts` |
| `packages/engine/` | WS1 | `shiftwright_engine` |
| `packages/validator/` | WS2 | `shiftwright_validator` |
| `data/laws/` | WS3 | (data) |
| `packages/scenarios/` | WS4 | `shiftwright_scenarios` |
| `packages/evals/` | WS5 | `shiftwright_evals` |
| `apps/api/` | WS6 | `shiftwright_api` |
| `apps/web/` | WS7 | React + Vite + TS + Tailwind |
| `packages/insights/` | WS8 (stretch) | `shiftwright_insights` |

`contracts/models.py` is the canonical file; `contracts/src/shiftwright_contracts/models.py` is a symlink to it so it installs as a package.

## Working in parallel

One worktree and branch per workstream, beside this checkout:

```bash
git worktree add ../sw-engine -b ws/engine
```

Small commits, rebase on `main` often, merge to `main` only with tests green. Keep your folder's `STATUS.md` current.
