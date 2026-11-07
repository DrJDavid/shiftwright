# Single service: FastAPI serving the built React app. Build from the REPO ROOT:
#   docker build -f apps/api/deploy/Dockerfile -t shiftwright .
# Railway: see apps/api/deploy/railway.toml (set the service's config path to it, or copy to the root).
FROM node:20-slim AS web
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY contracts ./contracts
COPY packages ./packages
COPY data ./data
COPY apps/api ./apps/api
RUN uv sync --no-dev
COPY --from=web /app/apps/web/dist ./apps/web/dist
ENV MESSENGER=mock \
    DATABASE_URL=sqlite:////data/shiftwright.db \
    WEB_DIST=/app/apps/web/dist \
    PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "mkdir -p /data && uv run --no-sync uvicorn shiftwright_api.main:app --host 0.0.0.0 --port ${PORT}"]
