# ArchFlow Progress

> Auto-generated from backlog.yaml — do not edit manually

## Dashboard

| Workstream | Status | Progress | Current Focus |
|-----------|--------|----------|---------------|
| Canvas polish | Archived | 0/0 | — |
| Visual Groups (IcePanel-style spatial grouping) | Archived | 0/0 | — |
| Multi-diagram drafts (features span many diagrams) | Archived | 0/0 | — |
| C4 Nesting UX (L1 → L2 → L3 drill-down) | Archived | 0/0 | — |
| Project Setup & Infrastructure | Archived | 0/0 | — |
| Backend API Foundation | Archived | 0/0 | — |
| Frontend Canvas | Archived | 0/0 | — |
| Basic Authentication | Archived | 0/0 | — |
| JSON Import/Export | Archived | 0/0 | — |
| Model Objects Tree Panel | Planned | 0/0 | — |
| Object Detail Sidebar (Tabbed) | Planned | 0/0 | — |
| Groups & Visual Grouping | Planned | 0/0 | — |
| Global Search & Navigation | Planned | 0/0 | — |
| Home / Overview Page | Planned | 0/0 | — |
| Popup Object Picker | Planned | 0/0 | — |
| C4 Zoom Drill-Down Navigation | Planned | 0/0 | — |
| Edge Details & Customization | Planned | 0/0 | — |
| Node Customization & Styling | Planned | 0/0 | — |
| Phase 8 Polish + Enterprise | Archived | 0/0 | — |
| Model Versions & Conflict Resolution | Planned | 0/4 | — |
| Teams, Roles & Workspaces | Planned | 0/4 | — |
| Real-time Collaboration | Planned | 0/4 | — |
| API Keys, Webhooks, Rate Limiting | Planned | 3/3 | — |
| AI Features (beyond insights) | Planned | 0/4 | — |
| Enterprise SSO & Compliance | Planned | 0/3 | — |

**Active Phase:** API Keys & Webhooks (3/3 done)
**Phases:** ... Versions + Conflicts | ... Teams, Roles, Workspaces | ... Real-time Collaboration | >> API Keys & Webhooks | ... AI Features (extended) | ... Enterprise SSO

**In Progress:** —
**Blocked:** —
**Next Up:** —

---

## Changelog

### 2026-04-20 — Rate limiting via Redis
**Done:**
- Redis async client wired\nSliding-window limiter with sorted-set ZADD/ZREM/ZCARD + pipelined ops\nDefault 60/min + 1000/hr buckets; tightest bucket surfaces on denial\nenforce_rate_limit dependency replaces get_current_user on /api-keys and /webhooks, sets X-RateLimit-* headers + 429+Retry-After\nCaller keyed on api_key.id when ak_ auth, else user.id — separate budgets per key\n2 new tests (sliding behaviour + bucket priority); all 10 tests green

**Decisions:**
- Applied only to endpoints that already enforce auth. Retrofitting auth onto the rest of the app belongs in the teams-roles epic, not here.\nZADD/ZCARD with pipeline() — could be moved to a Lua script for true atomicity, but the current race window is microseconds and any overflow gets trimmed by the next request's ZREMRANGEBYSCORE.

**Issues:**
- None.

**Tasks touched:** N/A

---


### 2026-04-20 — Webhooks: signed outbound events
**Done:**
- Webhook model + migration\nService with HMAC-SHA256 signing, retry with backoff, auto-disable\nEvent emit wired into object/connection/diagram CRUD + draft.applied\nCRUD endpoints + test ping + event catalogue\nSettings page section with create dialog + secret-once reveal + Test button\nSession-scoped event loop in conftest fixes cross-test asyncpg teardown\n9 tests green (3 new + 6 existing)

**Decisions:**
- Emit at API layer (not service) so the API-level Pydantic response model is reused as the payload schema — ensures webhook consumers see the same JSON shape that REST clients see.\nBackground delivery uses a dedicated async_sessionmaker, not the request session, since that session closes before retry sleeps elapse.

**Issues:**
- None blocking; delivery races commit by a few ms (fire_and_forget scheduled at endpoint level, commit happens in get_db teardown). If a request rolls back after the emit schedule, a false event fires. Acceptable for MVP; can move to after-commit hooks if this ever bites.

**Tasks touched:** N/A

---


### 2026-04-20 — API Keys: Bearer auth + Settings UI
**Done:**
- ApiKey model + migration\nService (create/list/revoke/verify) with ak_-prefixed bcrypt-hashed secrets\nAuth dep recognises API-key Bearers alongside JWT\nCRUD endpoints POST/GET/DELETE /api-keys\nSettings page with create dialog + one-time secret reveal\nUnit + E2E tests all green

**Decisions:**
- Scope API keys to user_id for now; org_id/workspace_id columns will be added when teams-roles epic lands rather than pre-baking empty columns.\nStore 12-char prefix separately for DB lookup + UI display; bcrypt the full secret so we never persist plaintext.

**Issues:**
- pytest-asyncio auto mode creates per-test event loops; shared asyncpg engine can't survive switch, so the HTTP-level test was consolidated into one function.\nNote: permissions field is stored but not yet enforced at endpoint level — follow-up task will add per-scope checks on protected routes when writes are implemented.

**Tasks touched:** N/A

---


### 2026-04-16 — auto
charts/archflow: Chart.yaml, values.yaml, templates for backend+frontend Deployments+Services, Postgres StatefulSet+headless Service, Redis, config Secret, optional Ingress
Tasks touched: 


### 2026-04-16 — auto
GET /activity endpoint with target_type/user filters + pagination, /activity route + ActivityPage rendering color-coded timeline
Tasks touched: 


### 2026-04-16 — auto
mermaid_service detects C4 vs flowchart flavour, parses Person/System/Container/Rel or A[label]-->B[label] with optional |pipe| labels. POST /import/mermaid endpoint.
Tasks touched: 


### 2026-04-16 — auto
structurizr_service parser (workspace/model/person/softwareSystem/container/component + -> rels, nested braces = parent_id) and POST /import/structurizr
Tasks touched: 


### 2026-04-16 — auto
1 line in ArchFlowCanvas: onlyRenderVisibleElements prop enabled on ReactFlow
Tasks touched: 


### 2026-04-16 — auto
5 files / +124 / -34 — activeFilterValue in canvas-store, chip click-to-filter in FilterToolbar, matchesFilterValue dimming in ArchFlowCanvas. Reuses legend strip as group chip bar. Drag-to-reorganize deferred.
Tasks touched: 


### 2026-04-16 — auto
Included in afc24d7: C4Edge renders a numbered circular badge above the label for every step in the active branch. Currently-playing step turns green, others stay blue.
Tasks touched: 


### 2026-04-16 — auto
17 files / +999 / -31 — Flow model/schemas/service/migration/API, FlowsPanel + FlowEditor with per-step branch tag, FlowPlaybackBar with branch selector. Covers -009 (alt paths via step branch tag) and -010 (numbered step badges on edges) together.
Tasks touched: 


### 2026-04-16 — auto
5 files / +248 / -154 — overlay-utils helpers, node outline styling via canvas-store.activeFilter, FilterToolbar wired to store with legend strip
Tasks touched: 


### 2026-04-16 — auto
10 files / +538 / -23 — anthropic SDK, ai_service, POST /objects/{id}/insights, useGetInsights hook, InsightsModal. Feature gated on ANTHROPIC_API_KEY env.
Tasks touched: 


### 2026-04-16 — auto
Included in d76ab0b alongside detail-sidebar-005: note type was added to the CommentType enum from day one — the backend enum is {question, inaccuracy, idea, note} and the composer surfaces all four with their own icons/colors (❓🚩💡📝).
Tasks touched: 


### 2026-04-16 — auto
13 files / +631 / -16 — comments table+migration+CRUD service+API, CommentsSection UI with typed composer (Q/Inaccuracy/Idea/Note), inline edit/resolve/delete, resolved collapse. Covers both detail-sidebar-005 and detail-sidebar-007 (note type included).
Tasks touched: 


### 2026-04-16 — auto
11 files / +573 / -80 — activity_log model/service/schema/migration, object CRUD hooks, GET /objects/{id}/history, frontend useObjectHistory hook and History tab UI
Tasks touched: 


### 2026-04-16 — auto
Implemented in commit 41caf9a: canvas-store dependenciesFocus state, ArchFlowCanvas dims non-neighbor nodes/edges via opacity 0.15, banner with Clear/ESC, ObjectContextMenu wires the overlay on click. Direct neighbors only for v1; transitive depth can come later.
Tasks touched: 


### 2026-04-16 — Work session
**Done:**
- ViaSelector UI in EdgeSidebar for selecting pass-through objects. Stores via_object_ids in backend.

**Decisions:**
- None

**Issues:**
- Visual routing through waypoints deferred — just stores selection for now. Full path rendering requires custom edge geometry (Phase 7 candidate).

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- Popup via + button with search, existing objects list, quick-create buttons. Left tree now collapsible via top bar toggle.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- Zoom icon badge shown on nodes with child diagrams (part of c4-drill-down-001)

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- Drill-down via zoom icon button on nodes. Backend filter by scope_object_id. Click icon navigates to child diagram.

**Decisions:**
- None

**Issues:**
- Multi-child popup deferred — single click goes to first child diagram for now

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- Belongs to (clickable parent) + Diagrams list with navigate links. Backend endpoint /objects/{id}/diagrams

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- NodeResizer on C4Node and GroupNode with blue handles when selected. Session-only for now; persistence of width/height requires API extension (followup).

**Decisions:**
- None

**Issues:**
- Resize is visual only - width/height not yet persisted to backend (diagram_objects has the columns, just need to wire up)

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- Distinct ActorNode (circle with person icon, name below) and ExternalSystemNode (dashed rounded rect with cloud icon). Different node types routed based on object.type.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- Flip button in EdgeSidebar toggles direction. Bidirectional edges render markerStart arrow on both ends.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- label_size field (8-20px) with slider. C4Edge renders configurable font size. Multi-line support via whitespace-pre-wrap and max-width 220px.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- Shape selector with 4 options (curved/straight/step/smoothstep), correct path rendering in C4Edge

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-16 — Work session
**Done:**
- EdgeSidebar component with Sender/Receiver, Direction+Flip, Shape selector, Label, Label size slider, Protocol, Delete

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Camera button in DiagramPage top bar, exports canvas as PNG via html-to-image

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- TipTap rich text editor: bold, italic, lists, code blocks. Auto-save with debounce. Replaces textarea in sidebar.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- GroupNode component with dashed border, visual container style. Groups rendered differently from regular C4 nodes.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Filter toolbar at bottom: Tags, Technology, Status, Teams tabs with count chips. Status colored per IcePanel reference.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Cross-references showing contains count (children) and connections count in Details tab

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Connections tab: incoming/outgoing with object names and labels. History tab placeholder. Details tab already had full editing.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- SearchModal: Cmd+K shortcut, searches objects (by name/description/tech) and diagrams, results grouped by type, click to navigate

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Breadcrumbs in DiagramPage (Home > Diagrams > name), home icon, back navigation

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Implemented as part of overview-page-001: diagrams grouped by C4 type (System Landscape, Context, Container, Component, Custom), create dialog with type selector

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Overview page with sidebar navigation, diagram cards grid by C4 type, create/delete dialogs. React Router setup with / (overview), /diagram/:id (canvas), /login (auth). Protected routes.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** overview-page-001,overview-page-002

---


### 2026-04-15 — Work session
**Done:**
- Diagram CRUD API: schemas, service, endpoints for diagrams + diagram_objects (per-diagram positions per ADR-002)

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** overview-page-003

---


### 2026-04-15 — Work session
**Done:**
- Quick-create buttons at bottom of tree panel: System, Actor, App, Store, Group with type icons

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- ObjectTree component: hierarchical tree, search/filter, expand/collapse, click to select on canvas, type icons

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- POST /api/v1/import endpoint with JSON parsing, ID remapping, parent_id resolution + TopBar Import JSON button with file upload

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- GET /api/v1/export endpoint + TopBar Export JSON button with file download

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Login/register UI page, auth store with localStorage persistence, auth guard in App, API interceptor with Bearer token

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- JWT auth: register/login/refresh endpoints, bcrypt hashing, access+refresh tokens, auth deps (get_current_user, get_optional_user)

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Status badge (colored dot) on C4Node component + status picker in sidebar. Colors: green=live, purple=future, orange=deprecated, red=removed

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Zustand canvas store (selectedNode, sidebar, filters) + React Query hooks for API (useObjects, useConnections, CRUD mutations with cache invalidation) + auth interceptor

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Add object toolbar with type selection, drag-to-move nodes, connect handles for drawing edges, delete from sidebar

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Tabbed sidebar (Details/Connections/History) with edit fields for all object properties, status picker, tag editor, delete button

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Custom C4Node component with type icons, status badges, technology tags, multi-handle connections. Custom C4Edge with labels and protocol. React Flow canvas with snap-to-grid, minimap, controls.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** frontend-canvas-002

---


### 2026-04-15 — Work session
**Done:**
- Already completed as part of project-setup-001: Vite + React + TS + TailwindCSS + Zustand + React Query + React Router + React Flow all scaffolded

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Connections CRUD: schemas, service layer, REST endpoints
- GET /between?src=&tgt= for querying connections between specific objects
- Source/target validation on create

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** backend-api-004

---


### 2026-04-15 — Work session
**Done:**
- Pydantic schemas (ObjectCreate/Update/Response) with field validation
- Service layer with async DB operations (CRUD + children + dependencies)
- REST endpoints: GET/POST/PUT/DELETE /api/v1/objects, /children, /dependencies
- Query filters by type, status, parent_id

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** backend-api-003

---


### 2026-04-15 — Work session
**Done:**
- Implemented as part of backend-api-002 — ObjectType enum includes system, actor, external_system, group, app, store, component. C4 level derived from type.

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Implemented as part of backend-api-002 — ObjectScope enum (internal/external), icon String(100) field

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- Implemented as part of backend-api-002 — ObjectStatus enum (live/future/deprecated/removed) with default=live, index on status column

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** N/A

---


### 2026-04-15 — Work session
**Done:**
- SQLAlchemy models for all core tables: model_objects, connections, diagrams, diagram_objects
- Extended type enum (system, actor, external_system, group, app, store, component)
- Status field (live/future/deprecated/removed) per ADR + IcePanel reference
- Scope field (internal/external) per IcePanel reference
- Per-diagram positions via diagram_objects junction table (ADR-002)
- Proper indexes on frequently queried columns

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** backend-api-002,backend-api-005,backend-api-006,backend-api-007

---


### 2026-04-15 — Work session
**Done:**
- Async SQLAlchemy engine with connection pooling
- Session factory with auto-commit/rollback in get_db dependency
- Base model with UUID and Timestamp mixins
- Alembic configured for async migrations with autogenerate from settings
- Health test still passing

**Decisions:**
- None

**Issues:**
- None

**Tasks touched:** backend-api-001

---


### 2026-04-15 — Work session
**Done:**
- Docker Compose created as part of project-setup-001:
- docker-compose.dev.yml: PG 16 + Redis 7 with health checks (for local dev)
- docker-compose.yml: Full stack (PG, Redis, backend, frontend, Caddy) for production
- Caddyfile: reverse proxy /api/ and /ws/ to backend, everything else to frontend
- Backend + Frontend Dockerfiles: multi-stage builds

**Decisions:**
- Dev compose only runs PG + Redis (app runs natively for hot reload on macOS)

**Issues:**
- None

**Tasks touched:** project-setup-002

---


### 2026-04-15 — Monorepo Structure Initialization
**Done:**
- Created full monorepo structure: frontend/, backend/, docker/, docs/
- Backend: FastAPI app with health endpoint, async config, pytest setup (1 test passing)
- Frontend: Vite + React + TypeScript + React Flow + TanStack Query + Zustand + TailwindCSS
- Docker: dev compose (PG + Redis), production compose (full stack + Caddy reverse proxy)
- Tooling: Makefile, orval API codegen config, vitest, ruff, .editorconfig

**Decisions:**
- Hybrid dev setup: PG+Redis in Docker, backend+frontend natively for hot reload
- uv as Python package manager
- orval for OpenAPI → TypeScript codegen with React Query hooks

**Issues:**
- None

**Tasks touched:** project-setup-001

---

