---
name: archflow-developer
description: Use when working in the ArchFlow repository (the C4-style architecture modeling tool at github.com/TheAlexPG/ArchFlow) — adding or modifying API endpoints, database models, React pages, tests, or migrations. Project-specific conventions for the FastAPI + SQLAlchemy + Pydantic backend and the React 19 + Vite + Zustand + React Query frontend, including realtime WebSocket fanout, Alembic migrations, and the PR-based contribution workflow.
---

# ArchFlow developer skill

## Overview

ArchFlow is a self-hostable, C4-style architecture modeling tool: users build hierarchical models out of **objects** (person, system, container, component, group), wire them with **connections**, and lay them out on **diagrams**. Everything is workspace-scoped. The web UI is real-time multi-user via WebSocket.

This skill captures conventions that aren't obvious from reading any single file: the layered backend pattern, the realtime fanout idiom, how the frontend consumes the API, and how the team handles branches/PRs/migrations.

## Stack at a glance

| Layer    | Tech                                                                                       |
| -------- | ------------------------------------------------------------------------------------------ |
| Backend  | FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, asyncpg, Alembic, Redis (pub/sub + rate-limit) |
| Frontend | React 19, Vite, TypeScript, TailwindCSS v4, React Router 7, Zustand, TanStack Query, axios, React Flow (`@xyflow/react`), Iconify |
| Auth     | JWT (access + refresh) **or** API key (`ak_` prefix); both ride the `Authorization: Bearer` header |
| Realtime | FastAPI WebSocket + Redis pub/sub for multi-instance fanout                                |
| Infra    | Docker Compose, Postgres 16, Redis 7, Caddy reverse proxy                                  |
| Tooling  | `uv` (Python deps), `npm` (Node deps), `make` (top-level orchestrator), `orval` (API client codegen), `ruff`, ESLint |

## Repository layout

```
ArchFlow/
├── backend/              # FastAPI service (uv-managed)
│   ├── app/
│   │   ├── api/v1/       # ⬅ HTTP/WS routers (one file per resource)
│   │   ├── api/deps.py   # get_current_user, get_optional_user, get_current_workspace_id
│   │   ├── api/permissions_dep.py  # require_role(Role.ADMIN) etc.
│   │   ├── api/rate_limit_dep.py
│   │   ├── core/         # config, database, security, permissions, rate_limit
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   ├── services/     # Business logic — routers MUST go through these
│   │   ├── realtime/     # WebSocket connection manager, Redis pub/sub
│   │   ├── ws/           # WebSocket helpers
│   │   └── main.py       # create_app() — registers every router
│   ├── alembic/versions/ # Migrations (one .py per revision)
│   ├── tests/            # pytest (api/, core/, services/)
│   └── pyproject.toml
├── frontend/             # Vite + React app
│   ├── src/
│   │   ├── api/          # orval-generated client (do not edit by hand)
│   │   ├── components/   # canvas/, sidebar/, tree/, toolbar/, nav/, auth/, ui/
│   │   ├── hooks/        # use-realtime, etc.
│   │   ├── pages/        # one .tsx per route + the /docs page subtree
│   │   ├── stores/       # Zustand stores (UI state only — server state lives in React Query)
│   │   ├── lib/api-client.ts  # axios instance with auth + X-Workspace-ID interceptors
│   │   └── App.tsx       # all <Route> definitions
│   └── package.json
├── docker/               # docker-compose.yml + dev override + Caddy + Postgres init
├── docs/                 # architecture/, api/ (markdown mirror), superpowers/ (specs+plans)
├── Makefile              # The only thing you need to remember to run
└── .github/workflows/    # CI = build Docker images on PR; deploy on push to main
```

## Setup, run, test, build

```bash
make setup        # one-time: deps + docker infra + initial DB migration + .env
make dev          # backend (uv run uvicorn ...:reload) + frontend (vite) + docker infra
make test         # pytest + vitest
make test-backend # only pytest
make test-frontend
make lint         # ruff + ruff format --check + eslint
make build        # docker compose -f docker/docker-compose.yml build
make up | down    # full prod stack via compose
```

Direct equivalents if you prefer not using make:

```bash
# Backend
cd backend && uv sync --all-extras
cd backend && uv run uvicorn app.main:app --reload
cd backend && uv run pytest -v
cd backend && uv run ruff check . && uv run ruff format --check .

# Frontend
cd frontend && npm install
cd frontend && npm run dev          # http://localhost:5173
cd frontend && npm run test         # vitest run
cd frontend && npm run build        # tsc -b && vite build
cd frontend && npm run lint
cd frontend && npm run api:generate # orval — regenerate after adding a backend endpoint

# Docker infra only (Postgres + Redis)
docker compose -f docker/docker-compose.dev.yml up -d
```

The backend test suite **requires Postgres + Redis** to be running (the dev compose stack provides both). Without them, ~half the suite fails with `redis.exceptions.ConnectionError` and async DB errors — that is environmental, not a code regression.

## Backend conventions

### Layered architecture (load-bearing)

Routers (`app/api/v1/*.py`) **must not** call SQLAlchemy directly for non-trivial logic. The flow is:

```
HTTP request
  → router (validates with Pydantic, applies auth deps)
    → service function (orchestrates DB + realtime + webhooks)
      → SQLAlchemy session (DB)
```

Routers should be thin: dependency-inject, call a service, fan out events, return. Services own the business logic and can be reused by tests, websocket handlers, or import scripts.

### Adding a new HTTP endpoint

1. **Schemas first** — add request/response models in `backend/app/schemas/<resource>.py`. Use Pydantic v2, `from_attributes=True`, and explicit field aliases when the model uses a Python keyword (see `metadata_: dict | None = Field(None, alias="metadata")` in `schemas/object.py`).
2. **Service function** — put the business logic in `backend/app/services/<resource>_service.py`. Accept `AsyncSession` plus typed args; return ORM objects or plain dicts; never raise `HTTPException` here.
3. **Router** — add to (or create) `backend/app/api/v1/<resource>.py`. Use the right deps:
   - `Depends(get_current_user)` — required JWT/API-key auth.
   - `Depends(get_optional_user)` — accept anonymous reads.
   - `Depends(get_current_workspace_id)` — resolve `X-Workspace-ID` header → membership-checked workspace UUID (or default workspace).
   - `Depends(require_role(Role.ADMIN))` — role-gated mutation. The 5-rank ladder is `viewer < reviewer < editor < admin < owner` (see `app/core/permissions.py`).
   - `Depends(enforce_rate_limit)` — sliding-window per-caller limit, scopes by API-key id when present.
4. **Register the router** in `backend/app/main.py:create_app()` with `app.include_router(<router>, prefix="/api/v1")`.
5. **Realtime + webhooks** — emit events from the router after a successful mutation. Use the helpers from `app/realtime/manager.py` (`fire_and_forget_publish`, `fire_and_forget_publish_diagram`) and `app/services/webhook_service.fire_and_forget_emit`. The pattern is "publish per workspace, then per-diagram for any diagrams that contain the touched object". `fanout` helpers in `app/api/v1/objects.py` and `connections.py` show the canonical shape.
6. **Tests** — add to `backend/tests/api/test_<resource>.py`. Use the `conftest.py` fixtures (`client`, `auth_user`, `workspace`).
7. **Frontend client** — run `cd frontend && npm run api:generate` to regenerate the orval client from the live OpenAPI doc. Commit the generated diff.

### Database & migrations

Models live under `backend/app/models/`. They use the SQLAlchemy 2.0 typed mapped-column style, with `UUIDMixin` + `TimestampMixin` from `models/base.py`. After changing a model:

```bash
cd backend && uv run alembic revision --autogenerate -m "add foo to bar"
# Inspect the generated revision in alembic/versions/ — autogen often misses
# server defaults, indexes on JSON columns, and enum changes. Edit before applying.
cd backend && uv run alembic upgrade head
```

Every upgrade **must** ship a working `downgrade()` (this is enforced in code review). Multi-step changes (e.g., NOT NULL add) need backfill migrations split into separate revisions.

### Realtime fanout (the part that surprises people)

The backend has **two** publish channels:

- **Workspace channel** (`workspace:<uuid>`) — every workspace member's UI subscribes via `useWorkspaceSocket()`. Used to invalidate React Query caches on object/connection/diagram CRUD.
- **Diagram channel** (`diagram:<uuid>`) — only callers viewing that diagram subscribe. Used for cursor presence, selection, and per-diagram-object placement events.

When you mutate an object that lives on multiple diagrams, you must fan out to **every diagram that contains it** before the row goes away — otherwise viewers of those diagrams won't refetch. See `_fanout_object_to_diagrams()` in `objects.py` and `_fanout_to_endpoint_diagrams()` in `connections.py` for the exact pattern. Capturing diagram membership *before* the delete is the trickiest part.

The Redis subscriber is started in `lifespan()` in `main.py`. Local dev needs `redis://localhost:6379/0` reachable.

### API keys vs JWT

Both auth modes resolve through `get_current_user` in `app/api/deps.py`. An API key whose secret starts with `ak_` is hashed-checked, then the owning user is loaded; from that point on the request looks identical to a JWT request. The `permissions` array on API keys is **not enforced today** — it's stored and echoed back, but every key inherits its owning user's full access. Workspace RBAC (`require_role`) gates against the user's `WorkspaceMember.role`, not the key's permission tokens.

WebSocket endpoints accept JWT only (passed as `?token=`), not API keys. See `backend/app/api/v1/websocket.py:_authenticate`.

## Frontend conventions

### Server state vs UI state

- **Server state** — TanStack Query. Use the orval-generated hooks in `frontend/src/api/`. The cache key includes the URL and query params; the `X-Workspace-ID` header is **not** part of the key, so when the user switches workspaces the app calls `queryClient.removeQueries()` (see `WorkspaceCacheReset` in `App.tsx`).
- **UI state** — Zustand stores under `frontend/src/stores/`. `auth-store` and `workspace-store` are the two load-bearing ones. Never put server data in Zustand — it'll desync from React Query.

### Calling the API

`frontend/src/lib/api-client.ts` wraps axios with two interceptors: one stamps `Authorization: Bearer <token>` from `auth-store`, the other adds `X-Workspace-ID` from `workspace-store`. Always use the orval-generated hooks (`useListObjects`, `useCreateObject`, …) instead of raw axios — that way the workspace header and auth go through automatically.

### Adding a route / page

1. Create `frontend/src/pages/<Name>Page.tsx`. If the route is authed, do nothing special — the `<ProtectedRoute>` wrapper in `App.tsx` handles it.
2. Add an `import` and a `<Route>` in `frontend/src/App.tsx`. Public routes (`/terms`, `/privacy`, `/docs`) sit *outside* the `<ProtectedRoute>` blocks.
3. If the page lives in the authed shell, mirror an existing page (e.g., `ObjectsPage.tsx`) for the layout.

### Styling

TailwindCSS v4 with project-level CSS variables in `frontend/src/index.css` (look for `@theme { ... }`). The dark theme uses `--color-bg: #0a0a0b` and the brand coral `--color-coral: #FF6B35`. Use the design tokens (`bg-panel`, `border-base`, `text-2`, etc.) instead of hardcoded hex.

The `LegalLayout` (`frontend/src/pages/legal-layout.tsx`) is the canonical "public dark page" template; the `/docs` page reuses its visual chrome.

### Testing

- Vitest + jsdom + Testing Library. Test setup in `frontend/src/test-setup.ts`.
- Co-locate test files (`Foo.test.tsx`) next to components.
- `npm run test` is `vitest run` (CI mode); `npm run test:watch` for development.

## Git workflow

`main` is protected. **Never commit there directly.** The convention from `CONTRIBUTING.md`:

- Branch names: `<type>/<kebab-description>` where type ∈ `feat fix refactor perf docs chore test style`.
- Commit headlines: `<type>(<optional scope>): <imperative-mood summary>` (~70 chars). Body explains the *why*.
- PRs squash-merge into `main`; the PR title becomes the squash commit message.
- Local pre-PR checks: `make lint && make test`.
- CI (`.github/workflows/deploy.yml`) builds backend and frontend Docker images on every PR; deploy runs only after merge to main. Pytest itself is **not** in CI.
- Migrations must have a working `downgrade()`.
- No commented-out code in PRs — `git remembers`.
- Frontend PRs that change UI ship screenshots or short clips.

Use `gh pr create` for PRs. Title and body should match the structure used in recent PRs (`gh pr list --limit 5` to see examples).

## Where to look first

| You want to…                            | Open                                                  |
| --------------------------------------- | ----------------------------------------------------- |
| Understand the full HTTP surface        | `docs/api/index.md` (or visit `/docs` in the UI)      |
| See how auth resolves                   | `backend/app/api/deps.py`                             |
| Add a route                             | mirror `backend/app/api/v1/objects.py`                |
| Understand the realtime fanout          | `backend/app/realtime/manager.py` + the `_fanout_*` helpers in `objects.py`/`connections.py` |
| Find a frontend page                    | `frontend/src/pages/`                                 |
| Look at the design tokens               | `frontend/src/index.css` (the `@theme { ... }` block) |
| Read why something was decided          | `docs/architecture/DECISIONS.md`                      |
| Read the contribution rules             | `CONTRIBUTING.md`                                     |

## Common pitfalls

- **Forgetting the workspace header.** Workspace-scoped endpoints fall back to the user's *oldest* workspace if `X-Workspace-ID` is missing. This is a frequent source of "why are my objects in the wrong place?" bugs in scripts.
- **Skipping fanout.** A mutation that updates the DB but doesn't publish to the workspace channel won't show up in other users' UIs until a manual refresh.
- **Capturing relationships before delete.** When you delete an object/connection that fans out to diagrams, capture the diagram set *before* the delete — junction rows go with the row.
- **Hand-editing `frontend/src/api/`.** It's regenerated by `npm run api:generate`. Hand edits are lost on the next regeneration.
- **Bypassing the service layer.** Don't put queries directly in routers. Tests and WS handlers reuse the service layer; duplicating logic in a router will silently diverge.
- **Pushing to `main`.** Branch protection will reject it. Always branch and PR.
- **Running pytest without infra.** Many tests need Postgres + Redis; bring them up with `docker compose -f docker/docker-compose.dev.yml up -d` before running the suite.

## License

ArchFlow itself is AGPL-3.0. By contributing, you agree your contribution is licensed under the same terms — see `LICENSE` in the repo root.
