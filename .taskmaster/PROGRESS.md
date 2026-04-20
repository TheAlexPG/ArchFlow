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
| Model Versions & Conflict Resolution | Planned | 3/5 | — |
| Teams, Roles & Workspaces | Archived | 0/0 | — |
| Real-time Collaboration | Planned | 1/4 | — |
| API Keys, Webhooks, Rate Limiting | Archived | 0/0 | — |
| AI Features (beyond insights) | Planned | 0/4 | — |
| Enterprise SSO & Compliance | Planned | 0/3 | — |

**Active Phase:** Real-time Collaboration (1/5 done)
**Phases:** >> Real-time Collaboration | ... AI Features (extended) | ... Enterprise SSO

**In Progress:** —
**Blocked:** —
**Next Up:** —

---

## Changelog

### 2026-04-21 — WS + Redis backbone + cursor presence
**Done:**
- ConnectionManager with per-instance id + Redis pub/sub fan-out\nPer-diagram room for cursors/presence/selection; workspace-level firehose for query invalidation\nJWT auth via query param; cursor author stamped server-side\nREST endpoints publish object/connection/diagram events through fire_and_forget_publish\nFrontend: useDiagramSocket + useWorkspaceSocket + CursorsOverlay with deterministic per-user hues\n5 new plumbing tests — 31 total green

**Decisions:**
- Redis pattern-subscribe (ws:*) rather than subscribing per room — keeps the subscriber task count constant regardless of open diagrams.\nCursor frames carry _origin so publishing instance skips its own echo — correct Miro-like "don't see your own cursor" behaviour without maintaining a per-send skip list.\nWorkspaceSocketGate at App level rather than per-page so every authenticated view benefits from live query invalidation without touching each component.

**Issues:**
- End-to-end ws:// smoke through starlette TestClient hits a task-across-loop error with asyncpg — deferred to a browser/e2e harness. The plumbing is covered by direct manager tests which do catch the double-delivery bug that would otherwise break cursor UX.

**Tasks touched:** N/A

---


### 2026-04-21 — Revert to previous version
**Done:**
- revert_to_snapshot service upserts + deletes per kind, scoped to workspace\nReplays placements after restoring diagrams\nPOST /versions/{id}/revert endpoint (admin)\nRevert button on VersionsPage with confirm\nFires version.reverted webhook\n2 new tests (round-trip + rename restoration)

**Decisions:**
- Upsert-in-place rather than delete-all-then-insert — avoids touching FKs that point at object ids (placements, connections, etc.). Renames show up as updates on the existing row instead of new rows.

**Issues:**
- None.

**Tasks touched:** N/A

---


### 2026-04-21 — Conflict detection on draft apply
**Done:**
- conflict_service.compute_conflicts diffs main vs fork against base_version\nThree conflict types surfaced: both_edited, main_deleted_fork_edited, fork_deleted_main_edited\nGET /drafts/{id}/conflicts\nPOST /drafts/{id}/apply returns 409 with report body; ?force=true to override\nFrontend banner + Force-apply dialog on DraftDetailPage\nE2E test proves 409 without force and 200 with force

**Decisions:**
- Conflict gate is opt-in via 409 + force. Won't ever silently drop the fork's changes — the admin has to actively click Force apply. Matches how Git/GitHub surface merge conflicts.

**Issues:**
- Fork deletions not explicitly tracked yet (fork-delete/main-edit conflict type exists but can only fire if the user deletes on the fork via a tombstone — that path isn't in the service yet). Good enough for MVP: the common collision (both edit same node) is caught.

**Tasks touched:** N/A

---


### 2026-04-21 — Versions table + snapshot on apply
**Done:**
- versions table + drafts.base_version_id + VersionSource enum\nversion_service.create_snapshot serialises full workspace state to JSONB\napply_draft now snapshots post-merge via conflict_service.apply_with_snapshot\nGET /versions + /snapshot + /{id} + /compare endpoints\nVersionsPage UI with compare + source pills

**Decisions:**
- Snapshot = full workspace blob, not delta. Simpler diffs, fine at current scale, can switch to compacted deltas later if payload grows.\nFork auto-takes a base snapshot if none exists yet — otherwise the first ever draft would have no base to detect conflicts against.

**Issues:**
- None blocking. Snapshot label is monotonic v1.N — no semver intent yet; picking major/minor needs UX input.

**Tasks touched:** N/A

---


### 2026-04-20 — Google OAuth stub
**Done:**
- GET /auth/oauth/google/login returns stub authorize URL\nGET /auth/oauth/google/callback upserts user by email (stub: "code" = email), provisions personal workspace, issues tokens\nusers.auth_provider column tracks local vs google\nAuthPage "Continue with Google (stub)" button prompts for email and signs in\nRound-trip test proves token issue + is_new_user flag

**Decisions:**
- Kept endpoint shape identical to what a real OAuth flow would look like — login returns an authorize URL the frontend window.location.assign'es to, callback takes a code. When we swap the stub for real Google, the frontend doesn't change.

**Issues:**
- Stub, not production. Replace _mock_userinfo with real google-auth client (client_id/secret config) when going live. Other providers (GitHub, GitLab) not wired yet.

**Tasks touched:** N/A

---


### 2026-04-20 — Teams + per-diagram ACL
**Done:**
- Team + team_members tables; user can be in multiple teams\ndiagram_access(diagram_id, team_id, access_level) grant table\ncan_read_diagram/can_write_diagram/filter_visible_diagram_ids helpers with "no grants = open, any grant = restricted" semantics\nGET /diagrams and /diagrams/{id} enforce ACL for authenticated members\nTeamsPage split view + DiagramAccessModal from DiagramPage\nE2E test proves frontend dev sees only their team's restricted diagrams

**Decisions:**
- Chose "grants imply restriction" over a per-diagram boolean flag. Reason: it makes the admin's intent obvious — if they grant any team, that diagram is private; if they leave it alone, it stays workspace-wide. One place to look per diagram.

**Issues:**
- owner_team string column on model_objects not yet swapped for a team_id FK — that replacement is a data migration; keeping the string column while team ACL lands reduces blast radius.

**Tasks touched:** N/A

---


### 2026-04-20 — Roles + permissions + member management
**Done:**
- Role hierarchy helper + require_role(min) dependency factory\nInvite flow: direct-add if user exists, token-based invite otherwise\nMember CRUD endpoints protected by require_role(ADMIN) with last-owner protection\nMembersPage UI with invite form + role picker + remove\n5 new tests (invite direct-add, non-admin 403, last-owner demote guard, etc.)

**Decisions:**
- Last-owner guard lives in member_service rather than the endpoint so both update_member_role and remove_member share it.\nInvite returns its token in the response body for the stub flow. Real email delivery can be added later; this keeps the UI testable without SMTP.

**Issues:**
- Write endpoints (POST/PUT/DELETE on objects/connections/diagrams) still don't enforce role — only diagram read is scoped by ACL. Retrofitting auth onto the write side is queued for a follow-up task so that editors are downgraded to viewers for diagrams their team only has read on.

**Tasks touched:** N/A

---


### 2026-04-20 — Orgs + Workspaces schema + auto-provisioning
**Done:**
- orgs + workspaces + workspace_members tables with workspace_role enum\nAuto-create personal org+workspace+owner membership on /auth/register\nGET /workspaces + GET /workspaces/{id} with membership check (404 for non-members)\nget_current_workspace dependency resolves X-Workspace-ID header and falls back to personal ws\nNullable workspace_id FK on model_objects + diagrams + backfill\nFrontend: workspace-store zustand, axios interceptor, WorkspaceSwitcher in sidebar\n3 new tests — all 13 green

**Decisions:**
- Header-based workspace selection (X-Workspace-ID) over JWT claim. Reason: workspace can change per-request without reminting tokens, matches how orgs ship in Linear/GitHub/Slack; JWT gets reserved for identity.\nEnum values_callable — avoids the Python-attribute-name-vs-Postgres-label mismatch that bit this task on the first test run.

**Issues:**
- Scoping queries by current workspace is NOT enforced in this task. Most endpoints remain unauthenticated — retrofitting auth across the whole API is a separate follow-up that properly belongs under teams-roles-002 (roles & permissions). Same story for adding workspace_id to connections/comments/flows/activity_log — done only on model_objects + diagrams for now.

**Tasks touched:** N/A

---


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

