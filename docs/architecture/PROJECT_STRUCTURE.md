# ArchFlow — Project Structure

```
ArchFlow/
├── frontend/                    # React + TypeScript (Vite)
│   ├── src/
│   │   ├── api/                 # Generated API client (orval output)
│   │   ├── components/
│   │   │   ├── canvas/          # React Flow canvas, custom nodes/edges
│   │   │   ├── sidebar/         # Object detail sidebar (tabbed)
│   │   │   ├── tree/            # Model objects tree panel
│   │   │   ├── toolbar/         # Canvas toolbar (filters, actions)
│   │   │   ├── nav/             # Breadcrumbs, top bar
│   │   │   ├── auth/            # Login, register forms
│   │   │   └── common/          # Shared UI components
│   │   ├── hooks/               # Custom hooks (useWebSocket, useCanvas, etc.)
│   │   ├── stores/              # Zustand stores (UI state only)
│   │   ├── types/               # TypeScript types (beyond generated API types)
│   │   ├── utils/               # Helper functions
│   │   ├── pages/               # Route pages
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── orval.config.ts          # API client generation config
│   ├── tailwind.config.ts
│   ├── vite.config.ts
│   ├── vitest.config.ts
│   └── package.json
│
├── backend/                     # Python FastAPI
│   ├── app/
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── objects.py   # Model objects CRUD
│   │   │   │   ├── connections.py
│   │   │   │   ├── diagrams.py
│   │   │   │   ├── auth.py
│   │   │   │   └── export.py    # Import/export
│   │   │   └── deps.py          # Dependency injection (DB session, current user)
│   │   ├── core/
│   │   │   ├── config.py        # Settings (pydantic-settings)
│   │   │   ├── security.py      # JWT, password hashing
│   │   │   └── events.py        # Event bus (WebSocket + Redis pub/sub)
│   │   ├── models/              # SQLAlchemy ORM models
│   │   │   ├── base.py          # Base model, UUID mixin
│   │   │   ├── object.py        # ModelObject
│   │   │   ├── connection.py    # Connection
│   │   │   ├── diagram.py       # Diagram, DiagramObject (junction)
│   │   │   └── user.py          # User
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # Business logic layer
│   │   ├── ws/                  # WebSocket manager + handlers
│   │   └── main.py              # FastAPI app factory
│   ├── alembic/                 # Database migrations
│   │   ├── versions/
│   │   └── env.py
│   ├── tests/
│   │   ├── conftest.py          # Fixtures (async DB, test client)
│   │   ├── api/
│   │   └── services/
│   ├── alembic.ini
│   ├── pyproject.toml           # Poetry/uv
│   └── Dockerfile
│
├── docker/
│   ├── docker-compose.yml       # Full stack: backend, frontend, postgres, redis, caddy
│   ├── docker-compose.dev.yml   # Dev overrides (hot reload, debug)
│   ├── caddy/
│   │   └── Caddyfile            # Reverse proxy config
│   └── postgres/
│       └── init.sql             # Initial DB setup
│
├── docs/
│   ├── architecture/
│   │   ├── DECISIONS.md         # Architecture Decision Records
│   │   └── PROJECT_STRUCTURE.md # This file
│   └── api/                     # Generated OpenAPI spec output
│
├── archflow-spec.docx           # Functional specification
├── .taskmaster/                 # Taskmaster backlog
├── .gitignore
└── README.md
```

## Key Patterns

### API → Frontend Type Flow
```
FastAPI endpoints → OpenAPI 3.1 spec (auto) → orval → TypeScript client + React Query hooks
```
One command regenerates the entire typed API layer. No manual type maintenance.

### Event Flow (Real-Time)
```
API mutation → Service layer → DB write → Event bus (publish) → WebSocket broadcast → React Query invalidation
```
Phase 1: single-user, events trigger local cache invalidation.
Phase 4: Redis pub/sub distributes events across instances.

### State Architecture (Frontend)
```
React Query: server state (objects, connections, diagrams) — cached, auto-refreshed
Zustand: UI state (selected node, sidebar tab, zoom level, active filters) — ephemeral
WebSocket: real-time events → React Query cache invalidation
```
