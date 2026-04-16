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
