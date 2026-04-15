.PHONY: dev dev-infra dev-backend dev-frontend test test-backend test-frontend build up down db-migrate db-upgrade db-downgrade api-codegen lint

# ─── Development ───────────────────────────────────────────────

dev: dev-infra
	@echo "Starting backend and frontend..."
	@trap 'kill 0' EXIT; \
		$(MAKE) dev-backend & \
		$(MAKE) dev-frontend & \
		wait

dev-infra:
	docker compose -f docker/docker-compose.dev.yml up -d

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

# ─── Testing ───────────────────────────────────────────────────

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest -v

test-frontend:
	cd frontend && npm run test

# ─── Build & Deploy ───────────────────────────────────────────

build:
	docker compose -f docker/docker-compose.yml build

up:
	docker compose -f docker/docker-compose.yml up -d

down:
	docker compose -f docker/docker-compose.yml down

# ─── Database ──────────────────────────────────────────────────

db-migrate:
	cd backend && uv run alembic revision --autogenerate -m "$(msg)"

db-upgrade:
	cd backend && uv run alembic upgrade head

db-downgrade:
	cd backend && uv run alembic downgrade -1

# ─── Code Generation ──────────────────────────────────────────

api-codegen:
	cd frontend && npm run api:generate

# ─── Linting ──────────────────────────────────────────────────

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint
