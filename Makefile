.PHONY: install test types eval eval-quick dev dev-api dev-web

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

dev-api:
	uv run uvicorn shiftwright_api.main:app --reload --port 8000

dev-web:
	cd apps/web && npm run dev

dev:
	$(MAKE) -j2 dev-api dev-web
