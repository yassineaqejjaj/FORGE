# FORGE — common tasks. Run `make help` for the list.

COMPOSE ?= docker compose
BACKEND_DIR := backend
FRONTEND_DIR := frontend

# Host-side URLs of the compose infrastructure (used by dev-backend / dev-worker, run from backend/).
DEV_ENV := FORGE_DATABASE_URL=postgresql+asyncpg://forge:forge@localhost:5434/forge \
	FORGE_VALKEY_URL=redis://localhost:6381/0 \
	FORGE_DEMO_AGENTS_URL=http://localhost:8190

.DEFAULT_GOAL := help
.PHONY: help up down logs build ps migrate seed reseed infra test lint check dev-backend dev-worker dev-demo-agents dev-frontend gen-api

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

up: ## Build and start the whole platform (web on http://localhost:3100)
	$(COMPOSE) up -d --build

down: ## Stop the platform (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow the logs of every service
	$(COMPOSE) logs -f --tail=200

build: ## Build the images
	$(COMPOSE) build

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## Apply database migrations (inside the api container)
	$(COMPOSE) exec api alembic upgrade head

seed: ## Load the demo data set through the real services (runs the demo benchmark and experiment)
	$(COMPOSE) exec -T api python -m forge.seed $(SEED_ARGS)

reseed: ## Wipe the demo data and seed it again
	$(MAKE) seed SEED_ARGS=--reset

infra: ## Start only postgres and valkey (for dev-backend / tests)
	$(COMPOSE) up -d postgres valkey

test: ## Run the backend test suite (needs `make infra`)
	cd $(BACKEND_DIR) && uv run pytest

lint: ## Lint the backend (ruff, format, architecture contracts)
	cd $(BACKEND_DIR) && uv run ruff check forge tests && uv run ruff format --check forge tests && uv run lint-imports

check: lint test ## Lint + tests (backend) and lint + typecheck (frontend)
	cd $(BACKEND_DIR) && uv run mypy forge
	cd $(FRONTEND_DIR) && npm run lint && npm run typecheck

dev-backend: ## Run the API on the host with auto-reload (needs `make infra`)
	cd $(BACKEND_DIR) && $(DEV_ENV) uv run alembic upgrade head && \
		$(DEV_ENV) uv run uvicorn forge.api.main:app --reload --host 127.0.0.1 --port 8100

dev-worker: ## Run a worker (both queues) on the host
	cd $(BACKEND_DIR) && $(DEV_ENV) uv run python -m forge.workers

dev-demo-agents: ## Run the demo agents on the host (port 8190)
	cd $(BACKEND_DIR) && $(DEV_ENV) FORGE_OTLP_INGEST_URL=http://localhost:8100/v1/traces \
		uv run uvicorn forge.demo_agents.app:app --host 127.0.0.1 --port 8190

dev-frontend: ## Run the Next.js dev server on the host (proxy to http://localhost:8100)
	cd $(FRONTEND_DIR) && FORGE_API_URL=http://localhost:8100 npm run dev

gen-api: ## Regenerate the TypeScript API types from the running API's OpenAPI document
	cd $(FRONTEND_DIR) && npm run gen:api
