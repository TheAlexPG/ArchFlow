# ArchFlow

Self-hosted C4 architecture modeling platform — visual-first canvas for System → Container → Component drill-down, with drafts, comments, flows, and activity history.

**Stack:** FastAPI + async SQLAlchemy 2.0 + Postgres • React + @xyflow/react + TanStack Query + Zustand • Redis • Alembic • uv + npm.

---

## Quick start

One-time setup (installs deps, starts Postgres/Redis, runs migrations):

```bash
make setup
```

Then every time you want to code:

```bash
make dev
```

That starts:
- Docker infra (Postgres on `:5432`, Redis on `:6379`)
- Backend on `http://localhost:8000` (docs at `/docs`)
- Frontend on `http://localhost:5173`

Hit **Ctrl+C** once to tear both down.

---

## Commands

### Dev

| Command | What it does |
|---|---|
| `make dev` | Sync deps → start infra → run migrations → launch backend + frontend in parallel |
| `make dev-deps` | `uv sync` backend + `npm install` frontend |
| `make dev-infra` | Bring up Postgres + Redis via docker compose |
| `make dev-backend` | Backend only (uvicorn with `--reload`) |
| `make dev-frontend` | Frontend only (vite) |

### Database

| Command | What it does |
|---|---|
| `make db-upgrade` | Apply all pending migrations |
| `make db-migrate msg="your message"` | Generate a new Alembic migration from model diff |
| `make db-downgrade` | Roll back the last migration |

### API codegen

| Command | What it does |
|---|---|
| `make api-codegen` | Regenerate the typed frontend client from the backend OpenAPI schema (run after changing endpoints/schemas) |

### Tests & lint

| Command | What it does |
|---|---|
| `make test` | Backend (`pytest`) + frontend tests |
| `make test-backend` | Backend only |
| `make test-frontend` | Frontend only |
| `make lint` | `ruff check` + `ruff format --check` + frontend `npm run lint` |

### Build & deploy (prod compose)

| Command | What it does |
|---|---|
| `make build` | Build prod docker images |
| `make up` | Start the prod stack |
| `make down` | Stop the prod stack |

---

## Project layout

```
backend/   FastAPI app, SQLAlchemy models, Alembic migrations
frontend/  Vite + React app
docker/    docker-compose files (dev + prod)
docs/      Architecture notes and ADRs
```

---

## Troubleshooting

**Port 8000 or 5173 already in use**
```bash
lsof -ti tcp:8000 | xargs kill    # or tcp:5173
```

**Migrations out of sync after pulling**
```bash
make db-upgrade
```

**Stale frontend types after changing API**
```bash
make api-codegen
```

**Fresh Postgres** (wipes the volume — you'll lose all data):
```bash
docker compose -f docker/docker-compose.dev.yml down -v
make dev-infra && make db-upgrade
```

---

## Environment

Config lives in `.env` at the repo root (copied from `.env.example` on first `make setup`). Override there for non-default DB creds, Anthropic key for AI insights, etc.
