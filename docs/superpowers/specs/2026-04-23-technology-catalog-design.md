# Technology Catalog — Design Spec

**Status:** approved
**Date:** 2026-04-23
**Branch:** `feat/technology-catalog`
**Worktree:** `.worktrees/technology-catalog`

## Motivation

Today `model_objects.technology` and `connections.protocol` are free-text fields. Users can type anything, there is no icon, no filtering, no suggestion. IcePanel — our UX reference — ships a curated technology catalog (~1500 entries with icons, brand colors, categories) plus per-workspace custom technologies. This spec brings the same first-class concept to ArchFlow.

## Scope (v1)

- Built-in catalog of ~150 curated technologies, icons sourced from Iconify (`@iconify/react`).
- Per-workspace custom technologies ("light-custom"): user picks an Iconify icon and gives it a name. No SVG upload in v1 — tracked as future work.
- Unified catalog applies to both objects (multi-select) and connection protocols (single-select).
- Canvas shows the primary technology as a 20×20 badge in the node's top-left corner. Full list and reordering in the sidebar.
- Edge labels show protocol icon + name.
- Technology management page per workspace (list, create, edit, delete custom).

Out of scope (deferred to a later phase):

- Custom SVG upload + sanitization.
- Self-hosted Iconify server (public CDN is acceptable for v1).
- Protocol suggestions based on source/target object types.

## Architectural decisions (summary)

| Decision | Chosen | Alternatives considered |
|---|---|---|
| Icon source | Iconify via `@iconify/react` | Bundled spritesheet; SVG in DB |
| Custom tech | Light-custom (pick Iconify icon) | SVG upload; URL reference |
| Tech per object | Multiple, ordered array, first = primary | Single primary only |
| Tech on canvas | Badge in corner | Icon row under name; replace shape |
| Connection protocol | Uses same catalog | Keep free-text |
| Storage | Single `technologies` table, `workspace_id IS NULL` = built-in | Static JSON only; split tables |
| Object→tech link | `technology_ids: UUID[]` on object | Join table |

## Data model

### New table `technologies`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `workspace_id` | UUID? FK→workspaces, ON DELETE CASCADE | `NULL` = built-in, globally visible |
| `slug` | VARCHAR(64) | Stable identifier (`postgresql`, `figma`, `grpc`) |
| `name` | VARCHAR(120) | Display name |
| `iconify_name` | VARCHAR(120) | `logos:postgresql`, `simple-icons:figma` |
| `category` | ENUM `tech_category` | See below |
| `color` | VARCHAR(9)? | Brand color `#RRGGBB[AA]` |
| `aliases` | TEXT[]? | Search aliases (`pg` → PostgreSQL) |
| `created_by_user_id` | UUID? FK→users, ON DELETE SET NULL | For custom |
| `created_at`, `updated_at` | TIMESTAMPTZ | |

**Enum `tech_category`:** `language | framework | database | cloud | saas | tool | protocol | other`.

**Indexes:**

- Unique `(workspace_id, slug)` — permits same slug across workspaces and built-in.
- Index `workspace_id`, `category`.

### Changes to existing tables

- `model_objects.technology` (`VARCHAR[]`) → drop. Add `technology_ids UUID[]`. Order matters: `[0]` is primary, rendered as the canvas badge. No DB FK (array limitation in Postgres). Referential integrity enforced in service layer.
- `connections.protocol` (`VARCHAR`) → drop. Add `protocol_id UUID?`. Single protocol per connection.

### Migrations (ordered)

1. `create_technologies_table` — table + enum + indexes + Alembic data migration upserting ~150 curated built-in rows from `backend/data/technologies.json`.
2. `model_objects_technology_to_ids` — drop `technology` column, add `technology_ids UUID[]`. Pre-release project: existing free-text data is discarded (documented in PR).
3. `connections_protocol_to_id` — drop `protocol`, add `protocol_id UUID?`. Same data-loss note.

### Delete semantics for custom technologies

On `DELETE /technologies/{id}`:

1. Count references: `COUNT(*) FROM model_objects WHERE :id = ANY(technology_ids)` + `COUNT(*) FROM connections WHERE protocol_id = :id`.
2. If any references exist → `409 Conflict` with the counts in the response body. User must manually remove references first.
3. Built-in (workspace_id NULL) → `403 Forbidden`.

## Backend API

Base: `/api/v1/workspaces/{workspace_id}/technologies`.

| Method | Path | Purpose | Permissions |
|---|---|---|---|
| `GET` | `/` | List/search. Query: `q`, `category`, `scope=builtin\|custom\|all` (default `all`). | Any workspace member (incl. viewer). |
| `POST` | `/` | Create custom. Body: `{name, slug?, iconify_name, category, color?, aliases?}`. Auto-slug from name if absent. | editor+. |
| `PATCH` | `/{id}` | Edit custom. Built-in → 403. | editor+. |
| `DELETE` | `/{id}` | Delete custom. 409 if referenced. Built-in → 403. | editor+. |

Service: `backend/app/services/technology_service.py`.

- List query: `workspace_id IS NULL OR workspace_id = :ws`, ILIKE over `name`, `slug`, `aliases`. Sort: exact match → prefix match → category → name.
- Validation on create: unique `(workspace_id, slug)`, `iconify_name` matches `^[a-z0-9-]+:[a-z0-9-]+$`.

`activity_logs` entries: `entity_type=technology`, `action=created|updated|deleted` on custom mutations.

## Real-time

WebSocket broadcasts in room `workspace:{id}`:

- `technology.created` — payload: full `Technology` object.
- `technology.updated` — payload: full `Technology` object.
- `technology.deleted` — payload: `{id}`.

Only custom technologies broadcast. Built-in is immutable at runtime.

Frontend React Query invalidates `['technologies', workspaceId]` on any of these events.

## Frontend

New dependency: `@iconify/react` (lazy-loads icons from Iconify CDN; self-hosted option deferred).

### Type updates (`frontend/src/types/model.ts`)

```ts
export type TechCategory =
  | 'language' | 'framework' | 'database' | 'cloud'
  | 'saas' | 'tool' | 'protocol' | 'other'

export interface Technology {
  id: string
  workspace_id: string | null
  slug: string
  name: string
  iconify_name: string
  category: TechCategory
  color: string | null
  aliases: string[] | null
}
```

- `ModelObject.technology: string[]` → `technology_ids: string[]`.
- `Connection.protocol: string \| null` → `protocol_id: string \| null`.
- `ObjectCreate/Update`, `ConnectionCreate/Update` updated accordingly.

### New components (`frontend/src/components/tech/`)

1. `TechIcon.tsx` — `<TechIcon technology={...} size={20} />`. Wraps `@iconify/react`. Fallback on invalid name: `logos:generic-service` + console warning.
2. `TechBadge.tsx` — icon + optional name, category tooltip. Used inline in sidebar and canvas.
3. `TechnologyPicker.tsx` — server-side fuzzy-search combobox, grouped by category, "+ Create custom" in footer. Props: `selected`, `onChange`, `multi`.
4. `CustomTechModal.tsx` — create/edit form: name, auto-generated slug (editable), category dropdown, color picker, Iconify browser (search via public Iconify API `https://api.iconify.design/search?query=...&limit=48`, grid of icons, click to select).
5. `TechnologyManager.tsx` — page at `/ws/:slug/technologies`: list custom tech, edit/delete, create new.

### Integrations

- `canvas/SystemNode.tsx` / `AppNode.tsx` / `StoreNode.tsx` / etc. — render primary `TechIcon` (20×20) top-left corner of card. Optional light background from `color`.
- `sidebar/ObjectSidebar.tsx` — replace current tech input with `<TechnologyPicker multi>`. List `<TechBadge>` below, drag-to-reorder (first = primary).
- `sidebar/EdgeSidebar.tsx` — replace protocol input with `<TechnologyPicker>` (single, default filter `category=protocol`).
- `canvas/` edge labels — icon + text.
- `toolbar/FilterToolbar.tsx` — add "by technology" multi-select filter.

### React Query hooks (`frontend/src/api/`)

- `useTechnologies(wsId, { q, category, scope })` — `staleTime: 5 * 60 * 1000` (built-in stable).
- `useCreateCustomTech`, `useUpdateCustomTech`, `useDeleteCustomTech` — each invalidates `['technologies', wsId]`.
- WS listener: `technology.*` → `queryClient.invalidateQueries(['technologies', wsId])`.

### Error handling / edge cases

- Iconify CDN unreachable → text fallback (initials).
- Invalid `iconify_name` → fallback icon + console warning.
- Slug collision on custom create → toast "Such technology already exists".
- Deleting referenced custom tech → 409 → modal listing reference counts and offering navigation to first usage.

## Delivery plan

Backend and data layer can ship immediately (zero overlap with `feat/redesign-v1`). UI waits for redesign to merge — otherwise rework / rebase hell.

**Milestones:**

| # | Milestone | Can start now? |
|---|---|---|
| M1 | Schema + seed (migrations, model, JSON, seed data migration) | ✓ |
| M2 | Service + REST API + permissions + activity log | ✓ |
| M3 | Object/connection schema migrations + service validation + regression tests | ✓ |
| M4 | WS broadcast for technology events | ✓ |
| M5 | Frontend data layer: types, `@iconify/react` dep, React Query hooks, WS listener | ✓ |
| M6 | UI core: TechIcon, TechBadge, TechnologyPicker, CustomTechModal | **Wait for redesign-v1 merge** |
| M7 | UI integrations: canvas badges, sidebars, edge labels, filter | **Wait** |
| M8 | Technology management page | **Wait** |
| M9 | ADR + short README/USER_GUIDE section; record "SVG upload" + "self-hosted Iconify" as future work | end |

**Dependency chain:**

```
M1 → M2 → M3 → M4 → M5 → [redesign-v1 merged] → M6 → M7 → M8 → M9
```

Each milestone leaves the system in a working state. After M3 the schema is new; without UI there is just no picker yet.

## Testing

- **Unit:** service layer (list filters, unique constraints, validation, reference-count on delete).
- **Integration:** API endpoints for CRUD, permissions (viewer denied writes, editor allowed, admin allowed), 403 on built-in mutation, 409 on referenced delete.
- **Regression:** existing object/connection endpoints after M3 schema change.
- **WS:** events broadcast on create/update/delete custom, not broadcast on built-in.
- **Frontend:** React Query hooks with msw mocks; UI component tests (after M6).

## Open items / future work

- **SVG upload ("heavy-custom")** for internal tools not present in Iconify. Requires object storage, SVG sanitization (`svg-sanitizer` backend, `DOMPurify` frontend).
- **Self-hosted Iconify API** for air-gapped deployments and CDN independence.
- **Protocol auto-suggestions** — e.g. HTTP for App→App, JDBC for App→Store.
- **Technology migration tool** — bulk rename/merge across objects when workspace custom tech evolves.
