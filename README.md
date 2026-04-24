<div align="center">

# ArchFlow

### A self-hosted, visual-first C4 architecture platform

*Draw your systems the way you think about them.*
*Fork. Comment. Review. Ship.*

[![Deploy](https://github.com/TheAlexPG/ArchFlow/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/TheAlexPG/ArchFlow/actions/workflows/deploy.yml)
![License](https://img.shields.io/badge/license-AGPL--3.0-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Postgres](https://img.shields.io/badge/Postgres-16-336791?logo=postgresql&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/Tailwind-3-38BDF8?logo=tailwindcss&logoColor=white)

</div>

---

## What it is

**ArchFlow is an open-source alternative to IcePanel** — a collaborative, real-time workspace for modeling software architecture using the [C4 model](https://c4model.com).

Unlike Figma-for-architecture tools that end at "pretty boxes", ArchFlow treats your architecture as a **first-class data model**: every object has a type (system, container, component, actor…), a lifecycle status, relationships, drafts, version history, and team-level access control. Drill from a system landscape all the way down to components — the model stays consistent at every zoom level.

```
L1  System Landscape ──▶ System Context
                           │
L2                      Container
                           │
L3                      Component
```

---

## ✨ Features

### 🎨 Visual-first canvas
- **React Flow-powered editor** with snap-to-group, smart containment, and edge routing.
- **Live cursors, presence roster, and selection sync** — see your teammates edit in real time.
- **Optimistic drag & resize** — zero snap-back, WebSocket cache patching under the hood.
- **Comments on the canvas** — question pins, inaccuracy flags, ideas, notes.

### 🧱 C4-native data model
- Objects (`system` / `external_system` / `actor` / `app` / `store` / `component` / `group`) with status, technology, tags, owner team.
- Per-diagram positions — the **same** object can live on L1, L2, L3 with different coordinates on each canvas.
- C4-aware quick-create: place the right types for the level you're on, but also allow cross-level references.

### 🎛️ Technology catalog
- **~170 built-in technologies** (Python, PostgreSQL, Kafka, Figma, gRPC, Kubernetes…) with Iconify-backed logos and brand colors.
- Picker in the **object sidebar** (multi-select) and **edge sidebar** (single-select, filtered to protocols) — results group by category with fuzzy search over name / slug / aliases.
- Canvas renders the primary technology as a **corner badge** on every node and resolves protocol icons onto edge labels.
- Create **workspace-level custom technologies** — pick any Iconify icon for the logo, set your own name / slug / color / aliases.
- Dedicated **`/technologies` management page** lists built-in + custom entries with scope + category filters.

### 🔀 Drafts & reviews
- **Fork any diagram** into a draft that lives in isolation from live data.
- Edit the fork freely — compare diffs, resolve conflicts with the live model, then merge.
- Full **version snapshots** with revert-to-version.

### 👥 Workspaces, teams, invites
- Multi-workspace with per-workspace roles (`owner` / `admin` / `editor` / `viewer`).
- **Per-diagram ACL via teams** — grant a team `read`/`edit`/`manage` access on individual diagrams.
- Pending-approval invite flow (invitee accepts; owner/admin approves).
- Notification inbox for mentions, invites, and activity.

### 📦 Organization at scale
- **Packs** — group diagrams into logical collections (like folders, but reorderable).
- **Pinned / Recent** on the Overview dashboard.
- Full-text search across all objects and diagrams (⌘K / Ctrl+K).

### 🔌 Extensibility
- **REST API** (OpenAPI / Swagger UI at `/docs`) + orval-generated TypeScript client.
- **API keys** with prefix-based detection (`ak_…`), first-class citizens alongside JWT.
- **Webhooks** for `object.*`, `connection.*`, `diagram.*`, and more.
- Optional **AI insights** (Claude) — summarize an object's role, spot missing connections.
- **JSON export / import** for migration or CI snapshotting.

### 🌐 Realtime collaboration
- One workspace-level WebSocket firehose + per-diagram channels.
- Keeps React Query cache in sync across tabs / users / browsers — no manual refresh.

---

## 🧰 Stack

<table>
<tr><td align="center" width="33%"><strong>Backend</strong></td><td align="center" width="33%"><strong>Frontend</strong></td><td align="center" width="33%"><strong>Infra</strong></td></tr>
<tr>
<td>

- FastAPI (async)
- SQLAlchemy 2.0 + asyncpg
- Alembic migrations
- PostgreSQL 16
- Redis (realtime fanout)
- pytest + pytest-asyncio
- uv package manager

</td>
<td>

- React 18 + Vite
- TypeScript 5
- @xyflow/react (canvas)
- TanStack Query
- Zustand (stores)
- TailwindCSS
- orval (codegen)

</td>
<td>

- Docker Compose (dev + prod)
- Helm chart (`charts/archflow`)
- GitHub Actions-ready
- `make`-driven developer flow

</td>
</tr>
</table>

---

## 🚀 Quick start

One-time bootstrap (installs deps, spins up Postgres/Redis, runs migrations):

```bash
make setup
```

Then any time you want to code:

```bash
make dev
```

That launches, in parallel:

| Service          | URL                        |
| ---------------- | -------------------------- |
| Backend (FastAPI) | `http://localhost:8000`    |
| API docs          | `http://localhost:8000/docs` |
| Frontend (Vite)   | `http://localhost:5173`    |
| Postgres          | `localhost:5432`           |
| Redis             | `localhost:6379`           |

One `Ctrl+C` tears both app processes down. Infra keeps running — `make down` stops the containers.

---

## 📜 Make targets

### Dev

| Command             | What it does                                                   |
| ------------------- | -------------------------------------------------------------- |
| `make dev`          | Deps → infra → migrations → backend + frontend in parallel     |
| `make dev-deps`     | `uv sync` backend, `npm install` frontend                      |
| `make dev-infra`    | Start Postgres + Redis via docker compose                      |
| `make dev-backend`  | Backend only (`uvicorn --reload`)                              |
| `make dev-frontend` | Frontend only (`vite`)                                         |

### Database

| Command                         | What it does                                     |
| ------------------------------- | ------------------------------------------------ |
| `make db-upgrade`               | Apply all pending migrations                     |
| `make db-migrate msg="..."`     | Generate a new Alembic migration from model diff |
| `make db-downgrade`             | Roll back the last migration                     |

### Tests, lint, codegen

| Command              | What it does                                                        |
| -------------------- | ------------------------------------------------------------------- |
| `make test`          | Backend `pytest` + frontend tests                                   |
| `make test-backend`  | Backend only                                                        |
| `make test-frontend` | Frontend only                                                       |
| `make lint`          | `ruff check` + `ruff format --check` + `npm run lint`               |
| `make api-codegen`   | Regenerate the typed frontend client from OpenAPI (run after schema changes) |

### Prod

| Command      | What it does              |
| ------------ | ------------------------- |
| `make build` | Build prod docker images  |
| `make up`    | Start the prod stack      |
| `make down`  | Stop the prod stack       |

---

## 🗂️ Project layout

```
ArchFlow/
├── backend/                  FastAPI app
│   ├── app/
│   │   ├── api/v1/           REST endpoints (one router per resource)
│   │   ├── models/           SQLAlchemy 2.0 models
│   │   ├── schemas/          Pydantic request/response schemas
│   │   ├── services/         Business logic layer
│   │   ├── realtime/         WebSocket manager + Redis fanout
│   │   └── core/             Config, DB, security
│   ├── alembic/              Migrations
│   └── tests/                Pytest suite
├── frontend/                 Vite + React SPA
│   └── src/
│       ├── pages/            Top-level routes
│       ├── components/       Canvas, sidebar, toolbar, modals…
│       ├── hooks/            React Query hooks + WebSocket client
│       ├── stores/           Zustand stores (auth, canvas, workspace)
│       ├── lib/              Shared axios client (auth + workspace + 401 → /login)
│       └── types/            Shared TypeScript models
├── docker/                   docker-compose.dev.yml + docker-compose.yml
├── charts/archflow/          Helm chart
└── docs/architecture/        ADRs + design notes
```

---

## 🧠 Concepts in 60 seconds

**Workspace** → your org's top-level container. Everything (diagrams, objects, teams, packs) belongs to exactly one workspace.

**Diagram** → a single C4-level canvas. Has a `type` (`system_landscape` · `system_context` · `container` · `component` · `custom`) and an optional `scope_object_id` linking it to its parent in the drill-down hierarchy.

**ModelObject** → a piece of your architecture (system, container, component, actor…). Lives in a workspace; can appear on many diagrams via a `DiagramObject` junction that stores per-diagram coordinates and size.

**Connection** → a directed or bidirectional edge between two ModelObjects. Rendered on any diagram that contains both endpoints.

**Draft** → a forked universe of a diagram + its objects + its connections. Changes stay isolated until you merge back into live.

**Pack** → a named collection of diagrams within a workspace, for organizing large architectures.

---

## 🧩 Environment

Config lives in `.env` at the repo root (copied from `.env.example` on first `make setup`). Knobs you'll touch most:

```env
DATABASE_URL=postgresql+asyncpg://archflow:archflow@localhost:5432/archflow
JWT_SECRET=change-me-in-production
BACKEND_CORS_ORIGINS=http://localhost:5173

# Optional — enables AI insights on ModelObjects
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 🐛 Troubleshooting

<details>
<summary><strong>Port 8000 or 5173 already in use</strong></summary>

```bash
lsof -ti tcp:8000 | xargs kill   # or tcp:5173
```
</details>

<details>
<summary><strong>Migrations out of sync after pulling</strong></summary>

```bash
make db-upgrade
```
</details>

<details>
<summary><strong>Stale frontend types after changing API</strong></summary>

```bash
make api-codegen
```
</details>

<details>
<summary><strong>Nuke Postgres (wipes the volume — you'll lose all data)</strong></summary>

```bash
docker compose -f docker/docker-compose.dev.yml down -v
make dev-infra && make db-upgrade
```
</details>

---

## 🗺️ Roadmap

- [x] C4 canvas with drill-down (L1 → L2 → L3)
- [x] Real-time collaboration (presence, cursors, selection, optimistic CRUD)
- [x] Drafts + diffs + conflict resolution
- [x] Version history with revert
- [x] Team-level per-diagram ACL
- [x] API keys + webhooks
- [x] Packs, pinned, search
- [ ] Import from Structurizr DSL
- [ ] Export to Mermaid / PlantUML
- [ ] SSO (OIDC)
- [ ] Deployment diagrams (C4 L4)

See [`docs/architecture/`](docs/architecture/) for ADRs and ongoing design.

---

## 🤝 Contributing

PRs welcome — bug fixes, features, docs, everything. Full workflow in
[CONTRIBUTING.md](CONTRIBUTING.md).

**TL;DR:**

1. `main` is protected. Branch off: `git switch -c feat/my-thing`.
2. Small, focused commits. Conventional prefixes: `feat/`, `fix/`,
   `refactor/`, `docs/`, `chore/`, `test/`.
3. Before pushing:

   ```bash
   make lint
   make test
   ```

4. Open a PR targeting `main`. CI runs `build-backend` and
   `build-frontend` — both must be green to merge.
5. Squash merge keeps `main` linear.

Bugs → [GitHub issues](https://github.com/TheAlexPG/ArchFlow/issues).
Security issues → [private advisories](https://github.com/TheAlexPG/ArchFlow/security/advisories).

---

## 📄 License

[AGPL-3.0](LICENSE) — free to use, modify, and self-host. If you run a modified version as a network service, you must offer the source under the same license.
