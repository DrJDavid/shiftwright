.PHONY: install test types eval eval-quick eval-mock dev dev-api dev-web

install:
	uv sync
	cd apps/web && npm install

test:
	uv run pytest

# contracts/models.py -> JSON Schema -> apps/web/src/contracts.ts (never hand-write these types)
types:
	uv run python scripts/export_schema.py > apps/web/src/contracts.schema.json
	cd apps/web && npx --yes json-schema-to-typescript@15 -i src/contracts.schema.json -o src/contracts.ts --unreachableDefinitions

eval:
	uv run python -m shiftwright_evals

eval-quick:
	uv run python -m shiftwright_evals --quick

# no API key needed: canned bad baseline outputs
eval-mock:
	uv run python -m shiftwright_evals --quick --mock-baselines

dev-api:
	set -a; [ -f .env ] && . ./.env; set +a; uv run uvicorn shiftwright_api.main:app --reload --reload-dir apps/api/src --reload-dir apps/api/prompts --reload-dir packages --reload-dir data/laws --reload-dir contracts --port 8000

dev-web:
	cd apps/web && npm run dev

dev:
	$(MAKE) -j2 dev-api dev-web
