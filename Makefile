.PHONY: dev dev-deps dev-infra dev-backend dev-frontend kill-dev setup test test-backend test-frontend build up down db-migrate db-upgrade db-downgrade db-sweep-undo api-codegen lint

# ─── Development ───────────────────────────────────────────────

dev: dev-deps dev-infra db-upgrade
	@echo "Starting backend and frontend..."
	@trap 'kill 0 2>/dev/null; pids=$$(lsof -ti tcp:8000,5173 2>/dev/null); [ -n "$$pids" ] && kill -9 $$pids 2>/dev/null; exit 0' INT TERM EXIT; \
		$(MAKE) dev-backend & \
		$(MAKE) dev-frontend & \
		wait

dev-deps:
	@echo "Syncing dependencies..."
	@cd backend && uv sync --all-extras --quiet
	@cd frontend && npm install --silent

dev-infra:
	docker compose -f docker/docker-compose.dev.yml up -d

# Pre-kill anything still bound to 8000 — uvicorn --reload sometimes orphans
# its worker on Ctrl+C while serving an SSE stream, leaving the port held.
dev-backend:
	-@pids=$$(lsof -ti tcp:8000 2>/dev/null); [ -n "$$pids" ] && kill -9 $$pids 2>/dev/null; true
	cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	-@pids=$$(lsof -ti tcp:5173 2>/dev/null); [ -n "$$pids" ] && kill -9 $$pids 2>/dev/null; true
	cd frontend && npm run dev

# Manual nuke — frees both dev ports without restarting.
kill-dev:
	-@pids=$$(lsof -ti tcp:8000,5173 2>/dev/null); [ -n "$$pids" ] && kill -9 $$pids 2>/dev/null; true
	@echo "Ports 8000 and 5173 freed."

setup: dev-deps dev-infra
	@echo "Running initial setup..."
	cd backend && uv run alembic revision --autogenerate -m "initial schema"
	cd backend && uv run alembic upgrade head
	@cp -n .env.example .env 2>/dev/null || true
	@echo "Done! Run 'make dev' to start."

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

db-sweep-undo:
	cd backend && uv run python -m app.jobs.undo_sweeper

# ─── Code Generation ──────────────────────────────────────────

api-codegen:
	cd frontend && npm run api:generate

# ─── Linting ──────────────────────────────────────────────────

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint
