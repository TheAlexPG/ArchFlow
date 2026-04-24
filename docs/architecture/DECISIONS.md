# Architecture Decision Records — ArchFlow

## ADR-001: Monorepo Structure
**Decision:** Flat layout with `frontend/`, `backend/`, `docker/`, `docs/` directories. No Turborepo/Nx.
**Rationale:** Simplicity. Type safety achieved via OpenAPI codegen, not shared code packages.

## ADR-002: Position Data Per-Diagram
**Decision:** Object positions stored in junction table `diagram_objects(diagram_id, object_id, position_data)`, NOT on `model_objects`.
**Rationale:** One object can appear on multiple diagrams with different positions. IcePanel shows "In 2 diagrams" — same object, different layouts.

## ADR-003: State Management
**Decision:** TanStack Query (React Query) for server state + Zustand for UI-only state (selected node, sidebar open, zoom level).
**Rationale:** React Query handles caching, invalidation, optimistic updates for API data. Zustand handles ephemeral UI state. Clean separation avoids stale data bugs.

## ADR-004: API Client Generation
**Decision:** FastAPI auto-generates OpenAPI 3.1 spec → orval generates TypeScript client + React Query hooks.
**Rationale:** Zero manual API client code. Type changes in backend automatically propagate to frontend on rebuild. Single source of truth.

## ADR-005: Real-Time from Phase 1
**Decision:** WebSocket infrastructure (FastAPI WebSocket + event bus) from Phase 1, even before multi-user.
**Rationale:** Avoids expensive refactor later. Phase 1 uses it for local reactivity (model changes reflected instantly). Phase 4 extends to multi-user presence/sync.

Architecture:
- Backend: FastAPI WebSocket endpoint + Redis pub/sub (even single-node benefits from pub/sub pattern)
- Frontend: WebSocket hook with auto-reconnect, message queue
- Events: `object.created`, `object.updated`, `object.deleted`, `connection.*`, `diagram.*`

## ADR-006: Auto-Layout Engine
**Decision:** Manual positioning as default. dagre library for optional "Auto-arrange" button.
**Rationale:** IcePanel is manual-first. Architects want precise control. Auto-arrange is a convenience, not the primary UX.

## ADR-007: Testing Strategy
**Decision:** Tests from Phase 1.
- Backend: pytest + httpx (async) + pytest-asyncio. TestContainers for PostgreSQL in CI.
- Frontend: Vitest + React Testing Library. MSW for API mocking.
- E2E: Playwright (added in Phase 2 when UI stabilizes).
**Rationale:** Retroactive testing is harder and lower quality. Test infrastructure is cheap to set up early.

## ADR-008: Rich Text Editor
**Decision:** TipTap (ProseMirror-based) for object descriptions.
**Rationale:** Battle-tested, extensible, works with collaborative editing (future Phase 4). Stores as JSON (TipTap native) with HTML export. Better than raw markdown for non-technical users.

## ADR-009: Database Schema Strategy
**Decision:** Normalized schema with selective JSONB.
- Core fields (name, type, status, parent_id, scope): normalized columns with proper indexes.
- Flexible fields (metadata, technology[], tags[]): JSONB/array columns.
- Alembic with auto-generation from SQLAlchemy models, reviewed before apply.
**Rationale:** Query performance for common operations (filter by type, status, team). Flexibility for custom metadata.

## ADR-010: Object Type System
**Decision:** Extended type enum: `system`, `actor`, `external_system`, `group`, `app`, `store`, `component`.
- `app` and `store` are container-level subtypes (app = service/application, store = database/cache/storage).
- `group` is a visual grouping container, separate from parent-child hierarchy.
- C4 level derived from type: system/actor/external_system → L1, app/store/group → L2, component → L3.
**Rationale:** Matches IcePanel's quick-create options. More intuitive than generic "container" for users.

## ADR-011: Authentication Architecture
**Decision:** JWT access tokens (short-lived, 15min) + refresh tokens (HTTP-only cookie, 7 days) + optional API keys.
- Phase 1: local email/password auth, single-user mode.
- Phase 4: OAuth2 (Google, GitHub, GitLab).
- Phase 8: SAML SSO.
**Rationale:** Standard, stateless, works with both browser and API clients.

## ADR-012: Technology Catalog
**Decision:** Replace the free-text `model_objects.technology[]` and `connections.protocol` fields with a first-class `technologies` table referenced by UUID.

**Storage and visibility.** One `technologies` table carries both the curated ~170-entry built-in set (`workspace_id IS NULL`) and workspace-scoped custom entries. Uniqueness is enforced with two partial indexes — `(slug) WHERE workspace_id IS NULL` and `(workspace_id, slug) WHERE workspace_id IS NOT NULL` — so a workspace can override a built-in slug locally and two workspaces can independently coin the same slug. Objects link via `technology_ids UUID[]` (order matters — first entry is the "primary" rendered on the canvas badge); connections link via a single `protocol_id UUID?`. Referential integrity is enforced in the service layer; Postgres doesn't support `FOREIGN KEY` on array elements, so we trade the DB constraint for application-side validation. PG enum values are the uppercase Python enum *names* (matching the rest of the repo's convention) — SQLAlchemy's default `Enum()` mapping uses names, so `TechCategory.LANGUAGE` round-trips as `'LANGUAGE'` in storage with `.value = "language"` on the Python side.

**Icon source: Iconify, not bundled SVGs.** Built-in rows reference Iconify names (`logos:postgresql`, `simple-icons:figma`). The frontend lazy-loads the actual SVG through `@iconify/react`, avoiding a ~10MB sprite bundle and letting us point at ~200k icons without hosting any ourselves. Trade-off: Iconify's CDN becomes a runtime dependency. Self-hosting the Iconify API is left as a follow-up for air-gapped deployments (see "Future work" below).

**Custom technology is light-custom for v1.** Users create a workspace custom entry by picking any Iconify icon plus a display name (modal searches `api.iconify.design/search` live). This avoids the storage / sanitization / CDN work that real SVG upload would need (see `docs/superpowers/specs/2026-04-23-technology-catalog-design.md` for the full scope analysis). Authentic internal logos that aren't in Iconify are the first use case for SVG upload — tracked as a future follow-up.

**Unified catalog for objects and connection protocols.** Instead of two parallel concepts ("technology" vs "protocol"), connections pick from the same catalog filtered to `category=protocol`. The picker component is reused verbatim between `ObjectSidebar` and `EdgeSidebar`, the same `TechIcon` renders on nodes and edge labels, and category filters on the management page cover both cases.

**Delete semantics.** Built-in rows are read-only at runtime (`403`). Deleting a custom row checks `model_objects.technology_ids` and `connections.protocol_id` via raw SQL; if any reference exists, the API returns `409` with `{object_refs, connection_refs, detail}`. The management page surfaces that body inline rather than generically failing. Rationale: silently orphaning references would corrupt the model; soft-deletion would complicate every query for limited benefit.

**Rationale.** Free-text breaks filtering, consistent naming, and icon rendering — three features users expect from an IcePanel-class tool on day one. A typed catalog costs us one migration per affected table and a single extra query per sidebar (deduped by React Query across the whole page) in exchange for those features and for cleanly versioning the catalog over time.

**Future work:**
- SVG upload with `svg-sanitizer` (backend) + `DOMPurify` (frontend) + object storage for truly internal logos.
- Self-hosted Iconify API for air-gapped / strict-egress customers.
- Protocol auto-suggestion from source/target object types (App→Store ⇒ suggest `jdbc`, App→App ⇒ `http`/`grpc`).
- Make the Mermaid and Structurizr importers workspace-aware so they can resolve the DSL's `technology`/`protocol` text against the catalog instead of dropping it.
- Bulk rename / merge tool for custom technologies whose slug evolves.
